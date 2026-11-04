"""A compute engine that reconstructs with Globus Compute, for the facility that runs it.

`conductor.adapters.globus_compute` declares what it needs of a compute
service and imports nothing, so something has to be the thing that
actually speaks to one. This is that, and it lives here rather than in
the package for the reason every profile does: it depends on a service
one facility happens to use, and most beamlines will never submit a job
through it.

`run.profile` names `reconstructions:engine`, and the entrypoint imports it before
it reads anything else, so a deployment that cannot import this stops at
startup rather than at the first reconstruction.

## What the command looks like, and why it is rendered here

One line, which the facility's own wrapper settled on:

    source <setup_env> && apptainer exec --nv --fakeroot --bind <b> \
        <image> tomocupy recon --flag value ...

The shape is code and the flags are data. That split is the whole of why
this file reimplements the rendering rather than importing the facility's
wrapper: its project declares `package = false` and says its scripts are
run rather than imported, so importing one by path would build on
something its author has said is not an interface, and his next refactor
would be this beamline's outage. What is actually worth sharing is the
flags, and those arrive as configuration rather than as code.

## Why a container path and a host path are both needed

The reconstruction runs inside a container with one directory bound into
it, so every path tomocupy is given is a container path while the
directories that have to exist beforehand are host paths. `_inside` and
`_outside` are the two directions of that bind. Getting them the wrong
way round produces a job that starts, cannot find its input, and exits
non-zero, which is exactly the failure the engine seam reports as a
refusal rather than as a success.

## Why the task id is resolved through the client and not through a future

A reconstruction outlives the walk that started it, so the usual outcome
is a handoff: the step ends with a task id and something else asks after
it later, possibly in another process after a restart. A future would be
gone by then. `Client.get_task` takes the id alone, which is what makes
the id worth recording.

## What this does not do

It does not retry, and it does not cancel. A reconstruction the service
refuses is reported as refused and one still running when the bound
expires is handed off, and both are decisions the engine seam already
makes. It also does not batch: one step is one dataset is one task, so
one step has one reference.
"""

from __future__ import annotations

import os
import shlex
import time
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Final

from alcf_tokens.auth import ServiceName, get_service_authorizer
from globus_compute_sdk import Client, Executor
from globus_compute_sdk.serialize import AllCodeStrategies, ComputeSerializer

from conductor.adapters.globus_compute import FAILED, SUCCEEDED, GlobusCompute, Said

if TYPE_CHECKING:
    from collections.abc import Mapping

ENDPOINT_VARIABLE: Final = "CORA_COMPUTE_ENDPOINT"
PROJECT_VARIABLE: Final = "CORA_COMPUTE_PROJECT"
QUEUE_VARIABLE: Final = "CORA_COMPUTE_QUEUE"
IMAGE_VARIABLE: Final = "CORA_COMPUTE_IMAGE"
SETUP_ENV_VARIABLE: Final = "CORA_COMPUTE_SETUP_ENV"
BIND_SOURCE_VARIABLE: Final = "CORA_COMPUTE_BIND_SOURCE"
BIND_TARGET_VARIABLE: Final = "CORA_COMPUTE_BIND_TARGET"
RESULTS_VARIABLE: Final = "CORA_COMPUTE_RESULTS"
DEFAULTS_VARIABLE: Final = "CORA_COMPUTE_DEFAULTS"
NODES_VARIABLE: Final = "CORA_COMPUTE_NODES"
WORKERS_VARIABLE: Final = "CORA_COMPUTE_WORKERS_PER_NODE"
ACCELERATORS_VARIABLE: Final = "CORA_COMPUTE_ACCELERATORS"
WALLTIME_VARIABLE: Final = "CORA_COMPUTE_WALLTIME"
ROUTINE_VARIABLE: Final = "CORA_COMPUTE_ROUTINE"
SETTLE_VARIABLE: Final = "CORA_COMPUTE_SETTLE_SECONDS"

DEFAULT_ROUTINE: Final = "reconstruct"
DEFAULT_QUEUE: Final = "demand"
DEFAULT_SUBCOMMAND: Final = "recon"

SERVICE: Final = "globus-compute"
"""Which of the facility's stored tokens this asks for.

Named rather than left to the client. A `Client` built with no
authorizer runs its own login, which on a terminal prompts and in a
service blocks forever: the process never finishes starting, systemd
restarts it, and it blocks again. Measured by hanging a probe on it.
"""

DEFAULT_SETTLE_SECONDS: Final = 900.0
"""How long a walk waits before handing a reconstruction off.

Fifteen minutes. Longer than the transfer engine's bound because a
reconstruction is slower, and still far shorter than one takes, so a
handoff is the ordinary outcome here rather than the exception. Nothing
is lost by guessing low: a handoff is a result rather than a failure.
"""

TASK_ID_TIMEOUT_SECONDS: Final = 120.0
"""How long to wait for the service to name the work.

`Executor.submit` returns before the id exists; a background thread
fills it in once the service acknowledges the batch. A submission that
never gets one is a submission nothing can ask after later, which is
worse than a refusal, so it is bounded and raises.
"""

CAPTURE_BYTES: Final = 20000
"""How much of the command's output to bring back, from each stream."""

TERMINAL: Final = {"success", "failed"}
"""The service's own words for work that has stopped."""


def _required(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(
            f"{name} is not set, so this compute engine does not know where or "
            "how to run a reconstruction. The unit file sets it."
        )
    return value


def _optional_int(name: str) -> int | None:
    value = os.environ.get(name, "").strip()
    return int(value) if value else None


def _reconstruct(job: dict[str, Any], timeout: int | None = None) -> dict[str, Any]:
    """Run one rendered command on the compute node.

    Everything is imported inside, because this function is serialized
    and executed somewhere that has none of this module's context.

    The container and the setup script are checked first. Sourcing a
    missing script aborts the shell chain with a bare "No such file",
    and apptainer's own complaint about a missing image is much noisier
    than saying which path was wrong.
    """
    import os
    import socket
    import subprocess
    import time

    started = time.time()
    command = job["command"]

    for key, what in (("image", "container image"), ("setup_env", "env setup script")):
        where = job.get(key)
        if where and os.path.isabs(where) and not os.path.exists(where):
            return {
                "returncode": None,
                "error": f"{what} not found on the compute node: {where}",
                "hostname": socket.getfqdn(),
                "stdout": "",
                "stderr": "",
                "elapsed_seconds": round(time.time() - started, 1),
            }

    for directory in job.get("makedirs") or []:
        os.makedirs(os.path.expandvars(directory), exist_ok=True)

    try:
        completed = subprocess.run(
            command,
            shell=True,
            # 'source' and the module commands a setup script uses are bash
            # builtins, and /bin/sh is dash on some systems.
            executable="/bin/bash",
            capture_output=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return {
            "returncode": -1,
            "error": f"the command did not finish inside {timeout} seconds",
            "hostname": socket.getfqdn(),
            "stdout": "",
            "stderr": "",
            "elapsed_seconds": round(time.time() - started, 1),
        }

    keep = job.get("capture_bytes") or 20000
    return {
        "returncode": completed.returncode,
        "error": "",
        "hostname": socket.getfqdn(),
        "stdout": completed.stdout.decode("utf-8", "replace")[-keep:],
        "stderr": completed.stderr.decode("utf-8", "replace")[-keep:],
        "elapsed_seconds": round(time.time() - started, 1),
    }


@dataclass(frozen=True, slots=True)
class GlobusComputes:
    """Submitting a reconstruction and asking after it, over Globus Compute.

    The two methods `Computing` declares, and the rendering that turns a
    dataset and a pile of settings into the one command that performs it.
    """

    client: Client
    endpoint: str
    user_endpoint_config: Mapping[str, Any]
    image: str
    setup_env: str
    bind_source: str
    bind_target: str
    results: str
    task_timeout: int | None = None

    def submit(
        self,
        *,
        source_path: str,
        settings: Mapping[str, object],
        label: str | None,
    ) -> str:
        executor = Executor(
            endpoint_id=self.endpoint,
            client=self.client,
            serializer=ComputeSerializer(strategy_code=AllCodeStrategies()),
            user_endpoint_config=dict(self.user_endpoint_config),
        )
        try:
            future = executor.submit(_reconstruct, self._job(source_path, settings, label))
            deadline = time.monotonic() + TASK_ID_TIMEOUT_SECONDS
            while future.task_id is None:
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        "the compute service did not name this work inside "
                        f"{TASK_ID_TIMEOUT_SECONDS:.0f} seconds, so nothing could ask "
                        "after it later"
                    )
                time.sleep(1.0)
            return str(future.task_id)
        finally:
            # Not waiting on it. The reconstruction outlives this call by
            # hours and the point of the id is that it can be asked after
            # from anywhere, including another process.
            executor.shutdown(wait=False, cancel_futures=False)

    def state(self, reference: str) -> Said:
        """What the service says, with a failing command read as a failure.

        The service answers whether it managed to run the command. A
        command that ran and exited non-zero is a task it calls
        successful, so the returned mapping is what decides, not the
        status.
        """
        task: Any = self.client.get_task(reference)
        status = str(task.get("status") or "").lower()
        if status not in TERMINAL:
            return Said(status or "pending")
        if status == "failed":
            return Said(FAILED, str(task.get("exception") or "the service reported no reason"))

        result: Any = self.client.get_result(reference)
        if not isinstance(result, dict):
            return Said(
                FAILED,
                f"the reconstruction returned {type(result).__name__} and not a result",
            )

        returncode = result.get("returncode")
        if returncode == 0:
            return Said(SUCCEEDED)
        return Said(FAILED, _why(result))

    def _job(
        self, source_path: str, settings: Mapping[str, object], label: str | None
    ) -> dict[str, Any]:
        """Everything the remote function needs for one reconstruction."""
        name = source_path.rstrip("/").rsplit("/", 1)[-1]
        out = f"{self.results.rstrip('/')}/{name}/"
        logs = f"{out}logs/"

        args: dict[str, object] = dict(settings)
        args["file-name"] = _inside(source_path, self.bind_source, self.bind_target)
        args["out-path-name"] = out
        args["logs-home"] = logs

        return {
            "name": label or name,
            "command": self._command(args),
            "image": self.image,
            "setup_env": self.setup_env,
            "capture_bytes": CAPTURE_BYTES,
            "makedirs": [
                _outside(out, self.bind_source, self.bind_target),
                _outside(logs, self.bind_source, self.bind_target),
            ],
        }

    def _command(self, args: Mapping[str, object]) -> str:
        argv = [
            "apptainer",
            "exec",
            "--nv",
            # Required on Polaris compute nodes; without it apptainer fails
            # with a starter-suid error.
            "--fakeroot",
            "--bind",
            f"{self.bind_source}:{self.bind_target}",
            self.image,
            "tomocupy",
            DEFAULT_SUBCOMMAND,
        ]
        for flag, value in args.items():
            argv.append("--" + str(flag).lstrip("-").replace("_", "-"))
            argv.append(_as_token(value))

        command = " ".join(shlex.quote(token) for token in argv)
        if self.setup_env:
            return f"source {shlex.quote(self.setup_env)} && {command}"
        return command


def _as_token(value: object) -> str:
    """One flag's value, spelled the way the command line wants it."""
    if isinstance(value, bool):
        return "True" if value else "False"
    return str(value)


def _inside(host_path: str, bind_source: str, bind_target: str) -> str:
    """A host path as the container sees it. Unchanged when it is not bound."""
    source, target = bind_source.rstrip("/"), bind_target.rstrip("/")
    if not source or not target:
        return host_path
    stripped = host_path.rstrip("/")
    if stripped == source:
        return target
    if stripped.startswith(source + "/"):
        return target + stripped[len(source) :]
    return host_path


def _outside(container_path: str, bind_source: str, bind_target: str) -> str:
    """A container path as the host sees it. Unchanged when it is not bound."""
    source, target = bind_source.rstrip("/"), bind_target.rstrip("/")
    if not source or not target:
        return container_path
    stripped = container_path.rstrip("/")
    if stripped == target:
        return source
    if stripped.startswith(target + "/"):
        return source + stripped[len(target) :]
    return container_path


def _why(result: Mapping[str, Any]) -> str:
    """The shortest honest account of a reconstruction that did not succeed."""
    said = result.get("error") or ""
    tail = (result.get("stderr") or "").strip().splitlines()
    if tail:
        said = f"{said} {tail[-1]}" if said else tail[-1]
    code = result.get("returncode")
    return f"exited {code}: {said}".strip() if said else f"exited {code}"


def _house_settings() -> Mapping[str, object]:
    """The reconstruction settings a step does not have to repeat.

    A file rather than an environment variable each, because there are
    dozens of them and a unit carrying dozens is a unit nobody reads. A
    step that names one overrides it, which is what makes the record say
    what was actually asked for.
    """
    where = os.environ.get(DEFAULTS_VARIABLE, "").strip()
    if not where:
        return {}
    settings: Any = tomllib.loads(Path(where).read_text(encoding="utf-8"))
    return settings.get("defaults") or {}


def _sizing() -> dict[str, Any]:
    """What the scheduler is asked for, which decides what the project is charged."""
    config: dict[str, Any] = {
        "account": _required(PROJECT_VARIABLE),
        "queue": os.environ.get(QUEUE_VARIABLE, "").strip() or DEFAULT_QUEUE,
        "launcher_type": "MpiExecLauncher",
        "scheduler_options": "\n".join(
            (
                "#PBS -l filesystems=home:eagle:grand",
                "#PBS -l place=scatter",
                "#PBS -l singularity_fakeroot=true",
            )
        ),
    }
    for variable, key in (
        (NODES_VARIABLE, "nodes_per_block"),
        (WORKERS_VARIABLE, "max_workers_per_node"),
        (ACCELERATORS_VARIABLE, "available_accelerators"),
    ):
        value = _optional_int(variable)
        if value is not None:
            config[key] = value
    walltime = os.environ.get(WALLTIME_VARIABLE, "").strip()
    if walltime:
        config["walltime"] = walltime
    return config


def engine() -> GlobusCompute:
    """Build the compute engine this deployment runs."""
    settle = os.environ.get(SETTLE_VARIABLE, "").strip()
    return GlobusCompute(
        computes=GlobusComputes(
            client=Client(authorizer=get_service_authorizer(ServiceName(SERVICE))),
            endpoint=_required(ENDPOINT_VARIABLE),
            user_endpoint_config=_sizing(),
            image=_required(IMAGE_VARIABLE),
            setup_env=os.environ.get(SETUP_ENV_VARIABLE, "").strip(),
            bind_source=_required(BIND_SOURCE_VARIABLE),
            bind_target=_required(BIND_TARGET_VARIABLE),
            results=_required(RESULTS_VARIABLE),
        ),
        routines=frozenset({os.environ.get(ROUTINE_VARIABLE, "").strip() or DEFAULT_ROUTINE}),
        settle_timeout=float(settle) if settle else DEFAULT_SETTLE_SECONDS,
        defaults=_house_settings(),
    )
