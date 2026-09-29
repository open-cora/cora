"""Answer questions about executions, and say what came of them.

    python -m thinker --config thinker.toml --serve
    python -m thinker --config thinker.toml --inquiry <id>
    python -m thinker --config thinker.toml --execution <id> --objective "..."

One command, no subcommands, and three ways to arrive at a question.
The first finds its own and keeps finding them, which is how a question
put over another surface is answered with nobody watching. The second
answers one that is already on the record and stops. The third opens one
and then answers it, which is what somebody at a terminal with an
execution in hand does.

All three end in a record. There is no way to think without leaving one,
and the absence is deliberate: a conclusion nobody can find afterwards is
the state the inquiry was added to end. It matters most in the first
mode, where the record is not one copy of the answer but the only one.

This is the one module allowed to name an adapter, which is what the rest
of the package's layering is for. `think` and everything in `seams` speak
in Protocols, so choosing a provider is a change to a configuration file
rather than to any of them.

## Why the answer still goes to stdout as JSON, in the modes that have one

It is no longer because there is nowhere else. All four conclusions reach
the record now, so this print is for whoever is waiting rather than for
posterity, and it carries two things the record does not: `said`, which is
the thinker's account of itself, and the shape of the case it read.

Serving prints no answer, for the same reason: nobody is waiting. What
it prints instead is a line per turn, which is a log rather than a
result, and `said` is lost there. That is the cost of running unattended
and it is worth naming, because it is the one thing a person reading an
inquiry afterwards cannot recover.

`said` stays out of the keeper by that record's design, on both the
proposal and the inquiry. Unbounded prose that will eventually quote a
person does not belong in a table nobody can edit afterwards, and this is
where it lives instead.

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

A fourth status says there was nothing to do. 3 is a question another
thinker already holds or has already answered, which is neither an answer
nor a fault: nothing broke, and nothing was concluded. Folding it into
either of those would tell a caller to retry something that is finished,
or to treat a healthy race as an outage.

Serving reaches only 0 and 2. A configuration still refuses to start,
and everything after that is the loop's to survive rather than to report:
a keeper that cannot be reached is waited out and tried again, and a
question another thinker took is the next turn. There is no third
outcome to spend a status on, because the process ends when it is told
to and not when something goes wrong.

## What is not caught, and what catching changes

A provider that raised. `think` does not catch it, and neither does a
one-shot run: it ends with a traceback and a status of 1.

Serving catches it, and that changes who tries again rather than what is
recorded. Nothing reaches the inquiry either way. A thinker that turned a
provider it could not reach into an abstention would be putting a finding
into the world that nothing found, which is the failure this package's
conclusions are four classes wide to avoid, and a loop that did it to
keep a question from sitting open would be doing it for a worse reason
than a command line ever had.
"""

from __future__ import annotations

import argparse
import importlib
import json
import signal
import sys
from pathlib import Path
from typing import TYPE_CHECKING, cast

import httpx

from thinker.adapters.http_keeper import TIMEOUT_MARGIN_SECONDS, HttpKeeper, KeeperError
from thinker.conclusions import Propose
from thinker.config import ConfigError, ThinkerConfig, load
from thinker.intake import DEFAULT_WAIT_SECONDS, serve
from thinker.think import think

if TYPE_CHECKING:
    from collections.abc import Sequence
    from types import FrameType

    from thinker.case import Question
    from thinker.seams import Concluding, Questioning
    from thinker.think import Thought

ALREADY_TAKEN = 3
"""The exit status for a question another thinker holds or has answered.

Its own number because it is neither of the two it would otherwise be
folded into. It is not 1, since nothing failed, and it is not 0, since
nothing was concluded and stdout carries no answer.
"""

REQUEST_TIMEOUT_SECONDS = 30.0
"""How long one request to the keeper may take before it counts as lost.

A floor rather than the whole answer. Serving raises it to cover the
wait it is about to ask for, because a client that times out before the
keeper answers turns every quiet ask into a failure.

Longer than `apps/conductor` allows itself, for the mode that has no
loop around it: a thinker asked about one execution has one chance at
each of its requests, and the cost of a timeout there is the whole run.
"""


def main(argv: Sequence[str] | None = None) -> int:
    """Load, build, and either think once or keep answering.

    Returns a shell exit status, which in serve mode is reached only by
    being told to stop.
    """
    arguments = _parse(argv)
    try:
        config = load(arguments.config)
        concluding = concluding_for(config)
    except ConfigError as problem:
        print(f"configuration: {problem}", file=sys.stderr)
        return 2

    timeout = max(REQUEST_TIMEOUT_SECONDS, arguments.wait + TIMEOUT_MARGIN_SECONDS)
    with httpx.Client(timeout=timeout) as http:
        keeper = HttpKeeper(http=http, base_url=config.base_url, token=config.token)
        if arguments.serve:
            return served(keeper, concluding, arguments)

        try:
            question = asked(keeper, arguments)
            if question is None:
                print("keeper: that inquiry is already taken up", file=sys.stderr)
                return ALREADY_TAKEN
            thought = think(
                question,
                observing=keeper,
                advising=keeper,
                concluding=concluding,
            )
        except KeeperError as refused:
            print(f"keeper: {refused}", file=sys.stderr)
            return 1

    print(json.dumps(reported(thought), indent=2))
    return 0


def served(
    keeper: HttpKeeper,
    concluding: Concluding,
    arguments: argparse.Namespace,
) -> int:
    """Answer questions until something stops this, and report that it stopped.

    Zero on the way out, because being told to stop is not a failure and
    is the only way out that is not an exception. Nothing else here
    returns a status: a conclusion is written to the record rather than
    reported to a caller, and a caller that wanted one would be waiting
    on a process that does not end.

    The keeper is passed as itself rather than as five arguments of one
    object, which is what it is: one adapter satisfying four seams. The
    loop is handed them separately because it is written against the
    seams, and this is the one module allowed to know they are the same
    thing.
    """
    stopping = False

    def keep_going() -> bool:
        return not stopping

    try:
        serve(
            keeper,
            questioning=keeper,
            observing=keeper,
            advising=keeper,
            concluding=concluding,
            wait=arguments.wait,
            keep_going=keep_going,
        )
    except KeyboardInterrupt:
        stopping = True
        print("\nstopping", file=sys.stderr)
    return 0


def asked(questioning: Questioning, arguments: argparse.Namespace) -> Question | None:
    """Settle which question this run is answering, or None if it lost it.

    Two ways in and one difference between them, which is whether anybody
    else could be holding the question.

    Named on the command line, it could be: the id came from somewhere and
    somewhere else may have it too, so this claims it and gives up if the
    claim is refused. Opened here, it could not be, because the id was
    minted a moment ago and nothing else has seen it, so no claim is made
    and none would say anything.

    That asymmetry is the whole of what the claim is for. It is not a lock
    and the record says so; what it buys is that two thinkers handed one
    question do not both spend an inference on it.
    """
    if arguments.inquiry is not None:
        if not questioning.claim(arguments.inquiry):
            return None
        return questioning.question(arguments.inquiry)
    return questioning.ask(arguments.execution, arguments.objective)


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
        "inquiry_id": thought.inquiry_id,
        "execution_id": thought.case.execution_id,
        "procedure": thought.case.procedure,
        "objective": thought.case.objective,
        "ran_to_the_end": thought.case.ran_to_the_end(),
        "unreached": len(thought.case.unreached()),
        "observed_step_count": thought.case.boundary().observed_step_count,
        "conclusion": type(conclusion).__name__.lower(),
        "said": conclusion.said,
        "proposal_id": thought.proposal_id,
    }
    if isinstance(conclusion, Propose):
        reading["operation_id"] = conclusion.operation_id
        reading["parameters"] = dict(conclusion.parameters)
    return reading


def concluding_for(config: ThinkerConfig) -> Concluding:
    """Build the provider seam the configuration named.

    The import happens at startup rather than at the moment of thinking,
    so a profile that is not importable is a message before an execution is
    read rather than a failure after two requests have been spent on it.

    What the named attribute returns is cast rather than checked.
    `Concluding` is a Protocol, so the check that matters is structural and
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

    return cast("Concluding", build())


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="thinker",
        description="Read one execution against its procedure and advise what to run next.",
    )
    parser.add_argument("--config", type=Path, required=True, help="path to thinker.toml")
    parser.add_argument(
        "--serve",
        action="store_true",
        help="keep answering whatever questions the keeper is holding",
    )
    parser.add_argument(
        "--wait",
        type=float,
        default=DEFAULT_WAIT_SECONDS,
        metavar="SECONDS",
        help="how long one request for a question may be held open before it answers empty",
    )
    parser.add_argument(
        "--inquiry",
        default=None,
        metavar="ID",
        help="answer a question already on the record",
    )
    parser.add_argument(
        "--execution",
        default=None,
        metavar="ID",
        help="open a question about this execution, then answer it",
    )
    parser.add_argument(
        "--objective",
        default=None,
        metavar="TEXT",
        help="what the thinking is toward, required when opening a question",
    )
    arguments = parser.parse_args(argv)

    named = arguments.inquiry is not None or arguments.execution is not None
    if arguments.serve:
        if named:
            parser.error("--serve finds its own questions; do not name one as well")
        return arguments

    if (arguments.inquiry is None) == (arguments.execution is None):
        parser.error("give --serve, or either --inquiry or --execution")
    if arguments.inquiry is not None and arguments.objective is not None:
        parser.error("--objective belongs with --execution; an inquiry already carries one")
    if arguments.execution is not None and arguments.objective is None:
        parser.error("--execution needs --objective, because an inquiry records what was asked")
    return arguments


def stop_on_termination() -> None:
    """Make a service manager's stop signal behave like Ctrl-C.

    Ctrl-C already arrives as `KeyboardInterrupt`, so the cheapest way
    to give both signals one shutdown is to make the second arrive that
    way too. Without this, the loop's orderly stop is reachable only
    from a keyboard, which a daemon does not have.

    Installed for every mode rather than only for the loop. A one-shot
    run is over too quickly for it to matter, and a handler that is
    installed only sometimes is one more thing about the entrypoint that
    depends on which flags were passed.
    """

    def interrupt(number: int, frame: FrameType | None) -> None:
        _ = number, frame
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupt)


if __name__ == "__main__":
    stop_on_termination()
    raise SystemExit(main())
