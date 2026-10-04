"""A thinking that asks a model, through the gateway this facility runs.

The third profile. Where the ladder knows one parameter and one ceiling,
both written into it, this one is handed the record and asked what to do
next. It is the thing the ladder exists to be measured against.

## The gateway answers failures the way it answers questions

This is the constraint the whole module is shaped by, and it was measured
rather than guessed. Two different failures came back as HTTP 200 with a
body in the ordinary answer shape:

    a username that is not authorized
        200, role assistant, with usage and a stop reason, and content
        reading "ACCESS DENIED ... not authorized"

    a request built wrongly
        200, and the complaint about it sitting in the field an answer
        would have been in

Neither is distinguishable from an answer by its status, and the first is
not distinguishable by its shape either. A profile that believed either
would write a conclusion onto an inquiry that nothing concluded, which is
the one thing `thinker.think` says must never happen: a thinker that could
not reach its provider has not abstained, and recording it as though it
had puts a finding into the world that nothing found.

**So the parse is the safety mechanism rather than a convenience.** What
comes back has to be exactly one JSON object carrying one of four known
words. Everything else raises, and raising stops the thinking without
writing anything. Both of the bodies above fail it, and both are fixtures
in this profile's suite.

## What the model is not asked

Whether the run went wrong. The record already holds two claims about how
each step ended and `outcomes` already reads them, so that is a lookup
rather than a judgement. A broken step or a failed engine is referred
before a prompt is built, which also means a gateway that is down or
wrong cannot turn a failed run into a request for more of it.

The model is asked the one question the record cannot answer: given a run
that finished cleanly and a goal, what is worth doing next.

## Where its settings come from

The profile factory is called with no arguments, and the thinker's
configuration deliberately holds no model settings, so these come from the
environment the unit sets. The keeper token is not among them: a unit file
in a shared home is world readable, and the token is read instead from the
configuration file at mode 600 that the service is already pointed at.
"""

from __future__ import annotations

import json
import os
from typing import TYPE_CHECKING, Any, Final, cast

import httpx
from outcomes import ended_badly, faulted

from thinker.conclusions import Abstain, Propose, Refer, Stop

if TYPE_CHECKING:
    from collections.abc import Mapping, Sequence

    from thinker.case import Case, Step
    from thinker.conclusions import Conclusion
    from thinker.seams import Concluding, Looking

URL_VARIABLE: Final = "CORA_ARGO_URL"
USER_VARIABLE: Final = "CORA_ARGO_USER"
MODEL_VARIABLE: Final = "CORA_ARGO_MODEL"

DEFAULT_MODEL: Final = "gpt4o"
TIMEOUT: Final = 120.0

RUN: Final = "run"
"""What the record calls a step that asks an engine to run something."""

WORDS: Final[frozenset[str]] = frozenset({"propose", "stop", "abstain", "refer"})
"""The only four answers this profile will accept.

A closed set, because the parse is what stands between a refusal that
looks like an answer and a finding on the record. Anything outside it is
treated as not an answer at all.
"""

INSTRUCTION: Final = (
    "You advise a synchrotron tomography beamline. You are given one execution, "
    "what it was asked to do, how it ended, what has been tried before, and the "
    "schema of the operation that can be run again.\n\n"
    "Answer with exactly one JSON object and nothing else. No prose, no code "
    "fence, no explanation outside the object.\n\n"
    '{"conclusion": "propose|stop|abstain|refer", "reason": "one sentence", '
    '"parameters": {}}\n\n'
    "Use propose only when another run is worth doing, and then parameters must "
    "satisfy the operation schema you were given, including every required "
    "property and every stated bound. Use stop when the objective is met. Use "
    "abstain when nothing here warrants another run. Use refer when a person "
    "should look. Include parameters only for propose."
)


class NotAnAnswerError(RuntimeError):
    """The gateway said something, and it was not a conclusion.

    Deliberately not a subclass of anything the thinking catches, because
    nothing catches it. A provider that answered with a refusal, a
    complaint, an apology or a code fence has not concluded, and the only
    honest thing to do with that is stop.
    """


class Argo:
    """Asks a model through the gateway, and believes only a parse."""

    def __init__(
        self,
        *,
        url: str,
        user: str,
        model: str,
        looking: Looking | None = None,
        http: Any = None,
    ) -> None:
        self._url = url
        self._user = user
        self._model = model
        self._record = looking
        self._http = http if http is not None else httpx

    def conclude(self, case: Case) -> Conclusion:
        """Say what should happen next, given what happened."""
        broken = [step for step in case.steps if faulted(step)]
        if broken:
            return Refer(
                said=(
                    f"{len(broken)} of {len(case.steps)} steps did not go well: "
                    f"{_listed(broken)}. The record says so, so this was not asked "
                    "of a model."
                )
            )

        unreached = case.unreached()
        if unreached and case.ended:
            return Refer(
                said=(
                    f"The execution was closed with {len(unreached)} of "
                    f"{len(case.steps)} steps never reached, and nothing here says "
                    "why. Somebody should read the record."
                )
            )
        if unreached:
            return Abstain(
                said=(
                    f"{len(unreached)} of {len(case.steps)} steps have not reported "
                    "and the execution is still open, so there is nothing to ask yet."
                )
            )

        runs = [step for step in case.steps if step.asked.get("kind") == RUN]
        if not runs:
            return Abstain(said="Nothing here asked an engine to run, so there is no run to weigh.")

        answered = self._ask(_prompt(case, runs[-1], self._context(case, runs[-1])))
        return _conclusion(answered, runs[-1])

    def _context(self, case: Case, run: Step) -> Mapping[str, Any]:
        """What the record can add, or nothing if there is no record to read.

        A profile built without one is the testable shape and the one a
        deployment never uses. Missing context narrows what the model can
        reason about; it does not licence a guess, which is why a record
        that is configured and unreachable raises instead of arriving here
        empty.
        """
        if self._record is None:
            return {}
        _ = run
        execution = self._record.execution(case.execution_id)
        # The seam hands back the record's own JSON, so the core types it
        # as object and the narrowing belongs here, where what the record
        # puts on an execution is known.
        walked = cast("Sequence[Mapping[str, Any]]", execution.get("steps") or [])
        operation = str(self._operation(case) or "")
        return {
            "operation_schema": self._record.operation_schema(operation) if operation else {},
            "datasets_this_run_produced": [
                {
                    "step": index,
                    "count": len(self._record.datasets_for(str(step["step_id"]))),
                }
                for index, step in enumerate(walked)
                if step.get("step_id")
            ],
        }

    def _operation(self, case: Case) -> object:
        """The operation the last run named, for asking about its schema."""
        runs = [step for step in case.steps if step.asked.get("kind") == RUN]
        return runs[-1].asked.get("operation_id") if runs else None

    def _ask(self, prompt: str) -> str:
        """One request, and the body as text.

        `messages` carries the instruction as a role rather than a
        `system` field beside it. The gateway refuses the two together,
        and it refuses them by answering, so getting this wrong produces
        a complaint in the place an answer goes.
        """
        payload = {
            "user": self._user,
            "model": self._model,
            "messages": [
                {"role": "system", "content": INSTRUCTION},
                {"role": "user", "content": prompt},
            ],
        }
        try:
            answered = self._http.post(self._url, json=payload, timeout=TIMEOUT)
        except Exception as unreachable:
            raise NotAnAnswerError(f"the gateway could not be reached: {unreachable}") from None
        if answered.status_code != 200:
            raise NotAnAnswerError(f"the gateway answered {answered.status_code}")
        return _text(answered.json())


def _text(body: Any) -> str:
    """The model's words, out of whichever shape the gateway used.

    Two are known: a bare `response` string, and a list of content parts
    the way an Anthropic-style reply is relayed. A body matching neither
    is not an answer, and saying so here keeps every caller from guessing.
    """
    if isinstance(body, dict):
        answered = cast("dict[str, Any]", body)
        response = answered.get("response")
        if isinstance(response, str):
            return response
        content = answered.get("content")
        if isinstance(content, list):
            parts = cast("list[Any]", content)
            return "".join(
                str(cast("dict[str, Any]", part).get("text", ""))
                for part in parts
                if isinstance(part, dict)
            )
    shown = str(cast("object", body))[:200]
    raise NotAnAnswerError(f"the gateway returned a body with no text in it: {shown}")


def _conclusion(answered: str, run: Step) -> Conclusion:
    """Turn the model's words into one of four conclusions, or refuse them.

    Strict on purpose. A lenient parse here is the route by which an
    access denial, a complaint about the request, or an apology becomes a
    finding on an inquiry, and all three arrive looking like answers.
    """
    try:
        parsed = json.loads(answered.strip())
    except ValueError:
        raise NotAnAnswerError(
            f"the gateway did not answer with one JSON object: {answered.strip()[:200]}"
        ) from None
    if not isinstance(parsed, dict):
        raise NotAnAnswerError(f"the gateway answered with {type(parsed).__name__}, not an object")

    said_object = cast("dict[str, Any]", parsed)
    word = str(said_object.get("conclusion", "")).strip().lower()
    if word not in WORDS:
        raise NotAnAnswerError(f"{word!r} is not one of the four conclusions")

    said = str(said_object.get("reason", "")).strip() or "no reason given"
    if word == "stop":
        return Stop(said=said)
    if word == "refer":
        return Refer(said=said)
    if word == "abstain":
        return Abstain(said=said)

    parameters = said_object.get("parameters")
    if not isinstance(parameters, dict) or not parameters:
        raise NotAnAnswerError("the gateway proposed a run and named no parameters for it")
    operation = run.asked.get("operation_id")
    if not operation:
        raise NotAnAnswerError("there is no operation to propose, so a proposal cannot be built")
    return Propose(
        operation_id=str(operation),
        parameters=cast_parameters(cast("dict[str, Any]", parameters)),
        said=said,
    )


def cast_parameters(parameters: Mapping[str, Any]) -> dict[str, Any]:
    """The proposed parameters, with their keys as strings.

    Nothing is coerced or dropped. Whether they satisfy the operation is
    the keeper's to say, and it says so by refusing the proposal, which
    is a better place for that check than here: this profile would be
    guessing at a schema the record holds.
    """
    return {str(name): value for name, value in parameters.items()}


def _listed(steps: list[Step]) -> str:
    """The steps by index and the word each ended on, for a `said`."""
    return ", ".join(f"step {step.index} {ended_badly(step)}" for step in steps)


def _prompt(case: Case, run: Step, context: Mapping[str, Any]) -> str:
    """Everything the model is given, as one block of JSON it can read."""
    asked: Sequence[Mapping[str, Any]] = [
        {
            "index": step.index,
            "asked": dict(step.asked),
            "ended": ended_badly(step),
        }
        for step in case.steps
    ]
    return json.dumps(
        {
            "objective": case.objective,
            "procedure": case.procedure,
            "execution_ended": case.ended,
            "steps": asked,
            "operation_to_run_again": run.asked.get("operation_id"),
            **context,
        },
        indent=2,
        default=str,
    )


def inference(looking: Looking) -> Concluding:
    """Hand back the thinking, which is what the profile setting calls.

    The environment is read here rather than at import, so a module that
    is imported for any other reason does not fail on a variable it does
    not need.

    `looking` arrives from the entrypoint, which is the one place this
    deployment's way to the record is built. This profile used to make
    its own, out of a configuration it loaded a second time, and that
    was a second credential path for a client the service already held.
    """
    url = os.environ.get(URL_VARIABLE, "")
    user = os.environ.get(USER_VARIABLE, "")
    if not url or not user:
        raise RuntimeError(
            f"{URL_VARIABLE} and {USER_VARIABLE} must both be set for this profile. "
            "The unit sets them, and the installer writes the unit."
        )
    return Argo(
        url=url,
        user=user,
        model=os.environ.get(MODEL_VARIABLE) or DEFAULT_MODEL,
        looking=looking,
    )
