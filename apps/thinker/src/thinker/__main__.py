"""Think once about one execution, and say what came of it.

    python -m thinker --config thinker.toml --execution <id> --objective "..."

One command and no subcommands. A thinker does one thing: it reads an
execution against the procedure it came from, forms a conclusion, and puts
a proposal forward if that is what it concluded.

This is the one module allowed to name an adapter, which is what the rest
of the package's layering is for. `think` and everything in `seams` speak
in Protocols, so choosing a provider is a change to a configuration file
rather than to any of them.

## Why the answer goes to stdout as JSON

Three of the four conclusions have nowhere else to go. The keeper records a
proposal and holds no vocabulary for a thinker that looked and advised
nothing, so a `Stop`, an `Abstain` and a `Refer` exist only in what this
prints. Something has to be able to read them, and a line of prose is a
thing to parse rather than a thing to read.

A `Propose` prints too, and its `said` is the part that exists only here:
the keeper has the plan and the parameters, and the reasoning stays out by
the design of its proposal event.

## Why a conclusion is never a failing exit status

It is tempting to exit non-zero on an `Abstain`, and it would be wrong.
The status says whether this thinker ran, not what it thought, and a caller
that read the two off one number would treat a thinker that reached a
provider and honestly saw nothing worth proposing as a thinker that broke.
Those want opposite handling: the first is an answer and the second is
worth retrying.

So every conclusion is 0, an error reaching the keeper or the provider is
1, and a configuration that will not load is 2. Which conclusion it was is
on stdout, where the rest of the answer already is.

## What is not caught

A provider that raised. `think` does not catch it, and neither does this:
the run ends with a traceback and a status of 1. A thinker that turned a
provider it could not reach into an abstention would be putting a finding
into the world that nothing found, which is the failure this package's
conclusions are four classes wide to avoid.
"""

from __future__ import annotations

import argparse
import importlib
import json
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx

from thinker.adapters.keeper_http import HttpKeeper, KeeperError
from thinker.conclusions import Propose
from thinker.config import ConfigError, ThinkerConfig, load
from thinker.think import think

if TYPE_CHECKING:
    from collections.abc import Sequence

    from thinker.seams import Inference
    from thinker.think import Thought

REQUEST_TIMEOUT_SECONDS = 30.0
"""How long one request to the keeper may take before it counts as lost.

Longer than `apps/conductor` allows itself, because that one retries and
this one does not: a thinker asked about an execution has one chance at
each of its three requests, and the cost of a timeout is the whole run
rather than one turn of a loop.
"""


def main(argv: Sequence[str] | None = None) -> int:
    """Load, build, think, and print. Returns a shell exit status."""
    arguments = _parse(argv)
    try:
        config = load(arguments.config)
        inference = inference_for(config)
    except ConfigError as problem:
        print(f"configuration: {problem}", file=sys.stderr)
        return 2

    with httpx.Client(timeout=REQUEST_TIMEOUT_SECONDS) as http:
        keeper = HttpKeeper(http=http, base_url=config.base_url, token=config.token)
        try:
            thought = think(
                arguments.execution,
                keeper=keeper,
                inference=inference,
                objective=arguments.objective,
            )
        except KeeperError as refused:
            print(f"keeper: {refused}", file=sys.stderr)
            return 1

    print(json.dumps(reported(thought), indent=2))
    return 0


def reported(thought: Thought) -> dict[str, object]:
    """The answer, in the shape something calling this can read.

    The conclusion's class is the field that matters and it travels as its
    own lowercased name, so a caller branches on a word rather than on
    which other fields happen to be present.

    `said` is here and does not reach the keeper. A proposal records what
    was proposed and refuses a reason by design, so this is the only place
    a thinker's account of itself exists at all.
    """
    conclusion = thought.conclusion
    reading: dict[str, object] = {
        "execution_id": thought.case.execution_id,
        "procedure": thought.case.procedure,
        "objective": thought.case.objective,
        "ran_to_the_end": thought.case.ran_to_the_end(),
        "unreached": len(thought.case.unreached()),
        "conclusion": type(conclusion).__name__.lower(),
        "said": conclusion.said,
        "proposal_id": thought.proposal_id,
    }
    if isinstance(conclusion, Propose):
        reading["plan_id"] = conclusion.plan_id
        reading["parameters"] = dict(conclusion.parameters)
    return reading


def inference_for(config: ThinkerConfig) -> Inference:
    """Build the provider seam the configuration named.

    The import happens at startup rather than at the moment of thinking,
    so a profile that is not importable is a message before an execution is
    read rather than a failure after two requests have been spent on it.

    What the named attribute returns is cast rather than checked.
    `Inference` is a Protocol, so the check that matters is structural and
    a deployment gets it from its own type checker. A runtime `isinstance`
    would confirm only that a method called `conclude` exists, which is the
    part a typo does not get wrong, and would refuse a perfectly good seam
    built by something older than this Protocol.
    """
    module_name, _, attribute = config.inference_profile.partition(":")
    try:
        module = importlib.import_module(module_name)
    except ImportError as missing:
        raise ConfigError(
            f"inference.profile names the module {module_name!r}, which will not import: {missing}"
        ) from missing

    build = getattr(module, attribute, None)
    if build is None:
        raise ConfigError(
            f"inference.profile names {attribute!r} in {module_name!r}, and there is "
            "nothing by that name there"
        )
    if not callable(build):
        raise ConfigError(
            f"inference.profile names {attribute!r} in {module_name!r}, which is not "
            "callable. It should be something that returns an inference seam."
        )

    return cast("Inference", build())


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="thinker",
        description="Read one execution against its procedure and advise what to run next.",
    )
    parser.add_argument("--config", type=Path, required=True, help="path to thinker.toml")
    parser.add_argument(
        "--execution",
        required=True,
        metavar="ID",
        help="the execution to think about",
    )
    parser.add_argument(
        "--objective",
        default=None,
        metavar="TEXT",
        help="what the run is in aid of, which no record holds and nothing can infer",
    )
    return parser.parse_args(argv)


if __name__ == "__main__":
    raise SystemExit(main())
