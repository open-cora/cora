"""Reads what an execution was asked to do and what became of it, and advises.

A client of the keeper rather than a part of it, the same way
`apps/conductor` and `apps/reporter` are. Nothing here imports `keeper` and
nothing in `apps/keeper` imports this.

What it is for, in one sentence: to be the thing that reads an execution
against the procedure it came from and says what should run next, so that
an agent proposing work is subject to the same record as a person
proposing it.

`think` is what `python -m thinker` runs, exported because a process that
already holds a keeper client and a provider would rather call it than
start a second one. It is given its seams, so importing this costs no
outside library.

## One thinking is of one question, whatever started it

A thinker is asked about one execution and answers once, and that is a
fact about `think` rather than about the process around it. Two things
start one: somebody naming a question on a command line, and `intake`,
which goes looking for a question nobody has taken up and answers it.

Going looking is not polling. The keeper holds the request open until
there is something to answer, so a waiting thinker is one open
connection rather than a question asked over and over, and the keeper
still dials nobody: being told that work exists arrives as the answer to
a call this side made.

What a thinker still cannot do is wake up part way through a run. No
command in the keeper touches a running execution, so a conclusion
reached while one is still walking has nowhere to arrive, and that is a
change to what the keeper and the conductor are rather than something
missing here.
"""

from thinker.case import Case, MismatchedCaseError, Reading, Step, assemble
from thinker.conclusions import Abstain, Conclusion, Propose, Refer, Stop
from thinker.config import ConfigError, ThinkerConfig, from_mapping, load
from thinker.seams import Advising, Concluding, Observing, Questioning, Seeking
from thinker.think import Thought, think

__all__ = [
    "Abstain",
    "Advising",
    "Case",
    "Concluding",
    "Conclusion",
    "ConfigError",
    "MismatchedCaseError",
    "Observing",
    "Propose",
    "Questioning",
    "Reading",
    "Refer",
    "Seeking",
    "Step",
    "Stop",
    "ThinkerConfig",
    "Thought",
    "assemble",
    "from_mapping",
    "load",
    "think",
]
