"""The sibling state this slice's decision needs, loaded before deciding.

The handler has already refused an execution with no stream behind it,
and a step that execution does not hold. What crosses here is the step
itself, because the decision reads one field off it: the plan it ran.

That is the difference from `register_dataset` next door, which makes
the same two checks and hands nothing across. Its decision needs the
step to exist and nothing more, so it has no context module at all. This
one compares, so the step is an input.

The step and not the execution around it. The execution is what makes
the step findable; once found, nothing about the traversal bears on
whether this acquisition ran the plan that was proposed.
"""

from dataclasses import dataclass

from aroc.execution.aggregates.execution import ExecutionStep


@dataclass(frozen=True)
class TakeProposalContext:
    """The acquisition being recorded against the proposal, as it stands.

    Read at handler time, so it can be stale by the time the append
    lands. What this check is for is catching a caller that resolved the
    wrong step, not racing one being reported.

    Staler than it looks, and harmlessly so. The two fields this reads,
    the step's id and the plan it runs, are fixed at the dispatch that
    created it and no later event touches either. What can change under
    this read is how the step went, which nothing here asks.
    """

    step: ExecutionStep


__all__ = ["TakeProposalContext"]
