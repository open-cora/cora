"""The turner's boot guard holds it while any pursuit is running, and only reads.

`infra/turner/no-pursuit-is-running.sh` is what the after-boot job runs before
it starts a turner nobody started. A turner that comes back moves every
running pursuit on at once, and the next step of a pursuit is a dispatch, so
after an outage of any length the pursuits wait for a person. The guard is
handed the unit's name, reads the interpreter, the configuration and the
certificate bundle out of that unit, and asks the keeper, as the turner,
which pursuits are running.

These run the script itself against a unit rendered from the template the
turner's installer renders and a keeper on the loopback, as the conductor's
guard is run beside this. The last cases pin the installer: it arms the job
with this guard and refuses a guard that cannot read the pursuits.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from conductor.adapters.http_turning import RUNNING
from tests._loopback_keeper import (
    Keeper,
    Request,
    certificate_bundle,
    executable,
    installed,
    render,
    run,
    serving,
    unreachable_url,
    wrapped_python,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

TURNER = Path(__file__).resolve().parents[1] / "infra" / "turner"
GUARD = TURNER / "no-pursuit-is-running.sh"
INSTALLER = TURNER / "install-turner.sh"

TOKEN = "the-turners-own-token"
UNIT = "turner.service"
"""A stand-in for the deployed name, which the guard reads from its argument."""


@pytest.fixture
def keeper() -> Iterator[Keeper]:
    with serving() as answering:
        yield answering


def _home(tmp_path: Path, *, base_url: str, python: str | None = None) -> Path:
    """A home holding the turner's unit, rendered from the shipped template."""
    interpreter = wrapped_python(tmp_path / "app")
    etc = tmp_path / "etc"
    etc.mkdir()
    config = etc / "turner.toml"
    config.write_text(
        f'[keeper]\nbase_url = "{base_url}"\ntoken = "{TOKEN}"\n',
        encoding="utf-8",
    )

    templates = sorted(TURNER.glob("*.service.in"))
    assert len(templates) == 1, f"expected the one turner template beside the guard: {templates}"
    unit = render(
        templates[0],
        {
            "@DEPLOY_HOST@": "this-host",
            "@PYTHON@": python or str(interpreter),
            "@CONFIG@": str(config),
            "@CA_BUNDLE@": str(certificate_bundle(etc)),
            "@LOG@": str(etc / "turner.log"),
        },
    )
    home = tmp_path / "home"
    installed(home, UNIT, unit)
    return home


def _running(pursuit_id: str, created_at: str) -> dict[str, str]:
    return {
        "pursuit_id": pursuit_id,
        "actor_id": "00000000-0000-0000-0000-000000000000",
        "goal": "a reconstruction good enough to segment",
        "beamline": "19-bm",
        "status": RUNNING,
        "created_at": created_at,
    }


def test_no_pursuit_running_lets_the_turner_start(tmp_path: Path, keeper: Keeper) -> None:
    home = _home(tmp_path, base_url=keeper.base_url)

    done = run(GUARD, home, UNIT)

    assert done.returncode == 0, done.stdout + done.stderr
    assert "no pursuit is running" in done.stdout


def test_the_guard_asks_as_the_turner_for_the_running_pursuits_and_only_reads(
    tmp_path: Path, keeper: Keeper
) -> None:
    keeper.items = [_running("p1", "2026-11-09T09:58:00Z")]
    home = _home(tmp_path, base_url=keeper.base_url)

    run(GUARD, home, UNIT)

    assert keeper.received == [
        Request(
            method="GET",
            path="/pursuits",
            query={"status": [RUNNING]},
            authorization=f"Bearer {TOKEN}",
        )
    ], "the guard asked for something other than the running pursuits, or wrote"


def test_pursuits_running_hold_the_turner_and_the_hold_names_each_one(
    tmp_path: Path, keeper: Keeper
) -> None:
    keeper.items = [
        _running("the-newer-one", "2026-11-09T10:30:00Z"),
        _running("the-older-one", "2026-11-09T09:58:00Z"),
    ]
    home = _home(tmp_path, base_url=keeper.base_url)

    done = run(GUARD, home, UNIT)

    assert done.returncode == 1, done.stdout + done.stderr
    assert "2 pursuit(s) are running" in done.stdout
    assert "a reconstruction good enough to segment" in done.stdout
    assert done.stdout.index("the-older-one") < done.stdout.index("the-newer-one")


def test_a_token_the_keeper_refuses_reads_as_pursuits_that_could_not_be_read(
    tmp_path: Path, keeper: Keeper
) -> None:
    keeper.status = 401
    home = _home(tmp_path, base_url=keeper.base_url)

    done = run(GUARD, home, UNIT)

    assert done.returncode == 2, done.stdout + done.stderr
    assert "could not be read" in done.stdout
    assert "401" in done.stdout


def test_a_keeper_that_cannot_be_reached_reads_as_pursuits_that_could_not_be_read(
    tmp_path: Path,
) -> None:
    home = _home(tmp_path, base_url=unreachable_url())

    done = run(GUARD, home, UNIT)

    assert done.returncode == 2, done.stdout + done.stderr


def test_a_question_that_crashes_reads_as_could_not_read_rather_than_pursuits_running(
    tmp_path: Path,
) -> None:
    crashing = executable(tmp_path / "crashing-python", "#!/bin/sh\necho Traceback >&2\nexit 1\n")
    home = _home(tmp_path, base_url=unreachable_url(), python=str(crashing))

    done = run(GUARD, home, UNIT)

    assert done.returncode == 2, (
        f"a crash came back as {done.returncode}. As 1 it would pass the installer, "
        "which accepts pursuits running, and then hold the turner after every boot"
    )


def test_the_installer_arms_the_job_for_the_turner_with_this_guard_beside_it() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert f'GUARD="${{SCRIPT_DIR}}/{GUARD.name}"' in text
    assert re.findall(r'after-boot\.sh" arm \S+ (.*)\)"$', text, re.M) == ['"${UNIT}=${GUARD}"']
    assert GUARD.stat().st_mode & 0o111, "the guard is not executable, so arming refuses it"


def test_the_installer_refuses_when_the_guard_cannot_read_the_pursuits() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    block = text[text.find('case "${guard}" in') :]

    assert 'if guard_said="$("${GUARD}" "${UNIT}")"; then' in text
    assert re.search(r"^\s*0\) ;;$", block, re.M)
    assert re.search(r"^\s*1\) say ", block, re.M)
    assert re.search(r"^\s*\*\) die ", block, re.M), (
        "a guard that cannot read the pursuits holds the turner after every boot "
        "the job acts on, so the deploy that would arm it has to fail"
    )
