"""Reads what an execution was asked to do and what became of it, and advises.

A client of the keeper rather than a part of it, the same way
`apps/conductor` and `apps/reporter` are. Nothing here imports `keeper` and
nothing in `apps/keeper` imports this.

What it is for, in one sentence: to be the thing that reads a run against
the routine it came from and says what should run next, so that an agent
proposing work is subject to the same record as a person proposing it.

`think` is what `python -m thinker` runs, exported because a process that
already holds a keeper client and a provider would rather call it than
start a second one. It is given its seams, so importing this costs no
outside library.

## Invoked, and not a loop

A thinker is asked once, about one execution, and answers once. Nothing in
this tree can tell a running process that something happened: the keeper is
dialled by its clients and dials nobody, and no event causes a write. So
a thinker cannot wake up when a run ends, and one written as a loop would
be one polling a record that nothing promised to change.
"""

from thinker.case import Case, MismatchedCaseError, Reading, Step, assemble
from thinker.conclusions import Abstain, Conclusion, Propose, Refer, Stop
from thinker.config import ConfigError, ThinkerConfig, from_mapping, load
from thinker.seams import Inference, Keeper
from thinker.think import Thought, think

__all__ = [
    "Abstain",
    "Case",
    "Conclusion",
    "ConfigError",
    "Inference",
    "Keeper",
    "MismatchedCaseError",
    "Propose",
    "Reading",
    "Refer",
    "Step",
    "Stop",
    "ThinkerConfig",
    "Thought",
    "assemble",
    "from_mapping",
    "load",
    "think",
]
