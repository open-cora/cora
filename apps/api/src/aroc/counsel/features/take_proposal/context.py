"""The sibling state this slice's decision needs, loaded before deciding.

The handler has already refused a run id with no stream behind it. What
crosses here is the run itself, because the decision reads one field off
it: the plan it ran.

That is the difference from `register_dataset` next door, which loads a
run and hands nothing across. Its decision needs the run to exist and
nothing more, so it has no context module at all. This one compares, so
the run is an input.
"""

from dataclasses import dataclass

from aroc.execution.aggregates.run import Run


@dataclass(frozen=True)
class TakeProposalContext:
    """The run being recorded against the proposal, as it stands now.

    Read at handler time, so it can be stale by the time the append
    lands. What this check is for is catching a caller that resolved the
    wrong run, not racing a run being reported.
    """

    run: Run


__all__ = ["TakeProposalContext"]
