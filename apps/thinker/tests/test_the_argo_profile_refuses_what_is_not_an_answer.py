"""The gateway answers failures the way it answers questions, and this refuses them.

`infra/thinking/argo.py` is the first profile here whose judgement comes
from outside, and the thing outside reports at least two kinds of failure
with HTTP 200 and a body in the ordinary answer shape. Both bodies in this
file were captured from the real gateway rather than imagined:

- a username the gateway knows and has not authorized
- a request built with `system` beside `messages`, which it refuses

Either one believed becomes a conclusion written onto an inquiry that
nothing concluded. That is the single failure `thinker.think` is explicit
about, so the parse is what is being tested here, more than the happy path.

Nothing here reaches the gateway. The profile takes its client, so every
case below is a canned body.
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from thinker.case import Case, Outcome, Step
from thinker.conclusions import Abstain, Propose, Refer, Stop

THINKING = Path(__file__).resolve().parents[1] / "infra" / "thinking"
if str(THINKING) not in sys.path:
    sys.path.insert(0, str(THINKING))

from argo import Argo, NotAnAnswerError  # noqa: E402

OPERATION = "01a0f82d-21ef-7050-b28f-5251a1e83f5b"

DENIED = {
    "id": "msg_blocked_svccora_1790948962",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "text",
            "text": (
                "\n\n IMPORTANT AUTHENTICATION NOTICE FROM ARGO \n\n ACCESS DENIED \n\n"
                "The username 'svccora' is not authorized to use the Argo Gateway API. "
                "Your ANL account was found but you do not appear in the authorized "
                "users list for your division."
            ),
        }
    ],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 0, "output_tokens": 0},
}
"""The real body a refused username produces, captured from the gateway."""

MISBUILT = {
    "response": (
        "You passed a messages field along with a system and or prompt field. "
        "Please only pass messages with any system and user prompts included, or "
        "only pass system and prompt alone."
    )
}
"""The real body a wrongly built request produces, captured from the gateway."""


@dataclass
class CannedGateway:
    """Answers every request with one body, and keeps what it was sent."""

    payload: Any
    status_code: int = 200
    sent: list[Mapping[str, Any]] = field(default_factory=list[Mapping[str, Any]])

    def post(self, url: str, *, json: Any = None, timeout: float | None = None) -> Any:
        _ = (url, timeout)
        self.sent.append(json or {})
        return _Answer(self.status_code, self.payload)


@dataclass
class _Answer:
    status_code: int
    payload: Any

    def json(self) -> Any:
        return self.payload


def _answering(body: Any, *, status: int = 200) -> tuple[Argo, CannedGateway]:
    gateway = CannedGateway(payload=body, status_code=status)
    return (
        Argo(url="https://gateway.example/chat", user="svccora", model="gpt4o", http=gateway),
        gateway,
    )


def _said(word: str, **extra: Any) -> dict[str, str]:
    return {"response": json.dumps({"conclusion": word, "reason": "because", **extra})}


def _run_step(*, index: int = 0, outcome: Outcome | None = None) -> Step:
    return Step(
        index=index,
        step_id=f"step-{index}",
        asked={
            "kind": "run",
            "operation_id": OPERATION,
            "parameters": {"NumAngles": 8, "ExposureTime": 0.05},
        },
        became=outcome if outcome is not None else Outcome("Done", "Completed", None),
    )


def _case(*steps: Step, ended: bool = True, objective: str | None = "resolve the edge") -> Case:
    return Case(
        execution_id="exec-1",
        procedure="sim scan 19-bm",
        steps=steps or (_run_step(),),
        ended=ended,
        objective=objective,
    )


def test_an_access_denial_shaped_like_an_answer_is_not_a_conclusion() -> None:
    """The one that would have shipped a denial onto the record as advice."""
    thinking, _ = _answering(DENIED)

    with pytest.raises(NotAnAnswerError):
        thinking.conclude(_case())


def test_a_complaint_about_the_request_is_not_a_conclusion() -> None:
    thinking, _ = _answering(MISBUILT)

    with pytest.raises(NotAnAnswerError):
        thinking.conclude(_case())


def test_prose_instead_of_an_object_is_not_a_conclusion() -> None:
    thinking, _ = _answering({"response": "I think you should run it again at 16 angles."})

    with pytest.raises(NotAnAnswerError):
        thinking.conclude(_case())


def test_a_fenced_object_is_not_a_conclusion() -> None:
    """A code fence is the most likely near miss, so it is refused by name."""
    thinking, _ = _answering({"response": '```json\n{"conclusion":"stop","reason":"done"}\n```'})

    with pytest.raises(NotAnAnswerError):
        thinking.conclude(_case())


def test_a_word_outside_the_four_is_not_a_conclusion() -> None:
    thinking, _ = _answering(_said("continue"))

    with pytest.raises(NotAnAnswerError):
        thinking.conclude(_case())


def test_a_proposal_naming_no_parameters_is_refused_rather_than_sent_empty() -> None:
    thinking, _ = _answering(_said("propose"))

    with pytest.raises(NotAnAnswerError):
        thinking.conclude(_case())


def test_a_body_with_no_text_anywhere_in_it_is_refused() -> None:
    thinking, _ = _answering({"unexpected": True})

    with pytest.raises(NotAnAnswerError):
        thinking.conclude(_case())


def test_a_gateway_that_refuses_outright_is_not_an_abstention() -> None:
    thinking, _ = _answering({"detail": "unauthorized"}, status=401)

    with pytest.raises(NotAnAnswerError):
        thinking.conclude(_case())


def test_a_broken_step_is_referred_without_asking_a_model_at_all() -> None:
    """The record already answers this, so a gateway cannot get it wrong.

    Asserted on the gateway having been sent nothing, not just on the
    conclusion, because a profile that asked and then ignored the answer
    would pass the weaker check.
    """
    thinking, gateway = _answering(_said("propose", parameters={"NumAngles": 16}))
    broken = Outcome("Broken", None, "TimeoutError")

    said = thinking.conclude(_case(_run_step(outcome=broken)))

    assert isinstance(said, Refer)
    assert gateway.sent == [], "a run the record calls broken was sent to a model anyway"


def test_a_run_reported_done_whose_engine_failed_never_reaches_the_model() -> None:
    thinking, gateway = _answering(_said("propose", parameters={"NumAngles": 16}))
    failed = Outcome("Done", "Failed", None)

    said = thinking.conclude(_case(_run_step(outcome=failed)))

    assert isinstance(said, Refer)
    assert gateway.sent == []


def test_the_instruction_is_sent_as_a_message_and_never_as_its_own_field() -> None:
    """The gateway refuses the two together, and refuses by answering.

    So this would not surface as an error. It would surface as a
    complaint in the field a conclusion is read from.
    """
    thinking, gateway = _answering(_said("abstain"))

    thinking.conclude(_case())

    sent = gateway.sent[0]
    assert "system" not in sent, "the gateway refuses a system field beside messages"
    assert sent["messages"][0]["role"] == "system"
    assert sent["messages"][1]["role"] == "user"


def test_the_configured_user_and_model_are_what_gets_sent() -> None:
    thinking, gateway = _answering(_said("abstain"))

    thinking.conclude(_case())

    assert gateway.sent[0]["user"] == "svccora"
    assert gateway.sent[0]["model"] == "gpt4o"


def test_a_proposal_carries_the_operation_the_run_named() -> None:
    thinking, _ = _answering(_said("propose", parameters={"NumAngles": 16}))

    said = thinking.conclude(_case())

    assert isinstance(said, Propose)
    assert said.operation_id == OPERATION
    assert said.parameters == {"NumAngles": 16}


@pytest.mark.parametrize(
    ("word", "expected"),
    [("stop", Stop), ("abstain", Abstain), ("refer", Refer)],
)
def test_each_conclusion_word_reaches_its_own_conclusion(word: str, expected: type) -> None:
    thinking, _ = _answering(_said(word))

    assert isinstance(thinking.conclude(_case()), expected)


def test_the_prompt_carries_the_objective_and_what_the_steps_asked_for() -> None:
    """Without these the model is guessing, and it answers anyway."""
    thinking, gateway = _answering(_said("abstain"))

    thinking.conclude(_case())

    prompt = gateway.sent[0]["messages"][1]["content"]
    assert "resolve the edge" in prompt
    assert "NumAngles" in prompt
    assert OPERATION in prompt


WALKED_STEP = "01a0fcd9-995e-72d2-8591-1f252d379c82"
"""A step's id as the execution walked it, which datasets are filed against."""

COMPOSED_STEP = "step-0"
"""The same step's id as the procedure composed it, which a case carries.

Two different ids for one step, and the record keeps them apart on
purpose. A dataset is registered against the first. A `Case` is built
from the procedure, so every step in one carries the second.
"""


@dataclass
class CannedRecord:
    """The record, answering the questions a profile asks of it."""

    beamline: str = "19-bm"
    schema: Mapping[str, Any] = field(default_factory=lambda: {"required": ["NumAngles"]})
    asked_beamlines: list[str] = field(default_factory=list[str])
    asked_steps: list[str] = field(default_factory=list[str])
    asked_procedures: list[str] = field(default_factory=list[str])

    def execution(self, execution_id: str) -> Mapping[str, Any]:
        _ = execution_id
        return {"beamline": self.beamline, "steps": [{"step_id": WALKED_STEP}]}

    def operation_schema(self, operation_id: str) -> Mapping[str, Any]:
        _ = operation_id
        return self.schema

    def prior_runs(self, beamline: str, limit: int = 10) -> list[Mapping[str, Any]]:
        _ = limit
        self.asked_beamlines.append(beamline)
        return [
            {"status": "Ended", "procedure_name": "tomo_scan", "procedure_id": "p1"},
            {"status": "Ended", "procedure_name": "tomo_scan", "procedure_id": "p1"},
        ]

    def datasets_for(self, step_id: str) -> list[Mapping[str, Any]]:
        self.asked_steps.append(step_id)
        return [{"dataset_id": "d1"}] if step_id == WALKED_STEP else []

    def procedure(self, procedure_id: str) -> Mapping[str, Any]:
        self.asked_procedures.append(procedure_id)
        return {
            "steps": [
                {"kind": "set", "record": "corasim19bm:Shutter", "to": 1.0},
                {"kind": "run", "parameters": {"NumAngles": 64, "ExposureTime": 0.05}},
            ]
        }


def test_the_beamline_is_read_off_the_execution_and_not_out_of_a_name() -> None:
    """The failure this cost a round, measured on the deployment.

    The beamline was once guessed from the procedure's name, and the
    procedures this system composes for itself are named after the
    operation and mention no beamline at all. The guess produced an empty
    beamline, the listing refused it, and the thinking stopped.

    A case whose procedure name contains nothing beamline-shaped must
    still ask the record for the right one.
    """
    gateway = CannedGateway(payload=_said("abstain"))
    record = CannedRecord(beamline="19-bm")
    thinking = Argo(
        url="https://gateway.example/chat",
        user="svccora",
        model="gpt4o",
        record=record,
        http=gateway,
    )

    thinking.conclude(
        Case(
            execution_id="exec-1",
            procedure="tomo_scan",
            steps=(_run_step(),),
            ended=True,
            objective="resolve the edge",
        )
    )

    assert record.asked_beamlines == ["19-bm"], (
        "the beamline did not come from the execution. Parsing it out of the "
        "procedure name is what broke against procedures named for an operation."
    )


def test_what_the_record_adds_reaches_the_prompt() -> None:
    """Context gathered and not sent is context that cost a request."""
    gateway = CannedGateway(payload=_said("abstain"))
    thinking = Argo(
        url="https://gateway.example/chat",
        user="svccora",
        model="gpt4o",
        record=CannedRecord(schema={"required": ["NumAngles"], "properties": {"NumAngles": {}}}),
        http=gateway,
    )

    thinking.conclude(_case())

    prompt = gateway.sent[0]["messages"][1]["content"]
    assert "operation_schema" in prompt
    assert "prior_runs" in prompt
    assert "datasets_this_run_produced" in prompt


def test_prior_runs_carry_the_parameters_they_were_given() -> None:
    """Status and a procedure name say only that something ran.

    A strategy stepping one parameter is being asked to pick the next
    value, and until now the runs it was shown to reason from all read
    alike: eight entries saying Ended, tomo_scan. The values those runs
    used were a read away on the procedure and were not fetched.
    """
    gateway = CannedGateway(payload=_said("abstain"))
    record = CannedRecord()
    thinking = Argo(
        url="https://gateway.example/chat",
        user="svccora",
        model="gpt4o",
        record=record,
        http=gateway,
    )

    thinking.conclude(_case())

    prior = json.loads(gateway.sent[0]["messages"][1]["content"])["prior_runs"]
    assert [run["parameters"] for run in prior] == [
        {"NumAngles": 64, "ExposureTime": 0.05},
        {"NumAngles": 64, "ExposureTime": 0.05},
    ]


def test_one_procedure_is_read_once_however_many_runs_used_it() -> None:
    """Procedures are reused: this beamline has run thirty-nine
    executions across eight of them, so a read per run would ask for the
    same document several times before every thinking.
    """
    gateway = CannedGateway(payload=_said("abstain"))
    record = CannedRecord()
    thinking = Argo(
        url="https://gateway.example/chat",
        user="svccora",
        model="gpt4o",
        record=record,
        http=gateway,
    )

    thinking.conclude(_case())

    assert record.asked_procedures == ["p1"], (
        f"two runs share one procedure and it was read {len(record.asked_procedures)} times"
    )


def test_datasets_are_counted_against_the_step_the_execution_walked() -> None:
    """The bug a model caught by reasoning correctly from bad context.

    A case is built from the procedure, so its steps carry the composed
    id. A dataset is filed against the walked id. Asking with the first
    always answers none, and the gateway was told a run that had filed
    data had produced nothing. It referred the case to a person, which
    was the right call on what it was given and the wrong call on what
    happened.

    The two ids look alike, and nothing fails when they are swapped, so
    this is pinned rather than left to reading.
    """
    gateway = CannedGateway(payload=_said("abstain"))
    record = CannedRecord()
    thinking = Argo(
        url="https://gateway.example/chat",
        user="svccora",
        model="gpt4o",
        record=record,
        http=gateway,
    )

    thinking.conclude(_case())

    assert record.asked_steps == [WALKED_STEP], (
        f"datasets were looked up by {record.asked_steps}, and the composed id "
        f"{COMPOSED_STEP!r} answers none for a run that filed data"
    )
    prompt = gateway.sent[0]["messages"][1]["content"]
    produced = json.loads(prompt)["datasets_this_run_produced"]
    assert produced == [{"step": 0, "count": 1}], (
        "a total across steps hides which step produced nothing, which is the "
        "shape this system exists to notice"
    )
