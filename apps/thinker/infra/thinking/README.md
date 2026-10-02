# The thinking this repository ships

`inference.profile` names something importable that hands back whatever
concludes. Until this directory existed there was nothing here to name, so
an installed thinker had no way to start: the entrypoint imports the
profile before it reads anything, and a path naming nothing stops it there.

Two of them now, and a deployment picks one by its dotted path. Neither is
the only possible one: a deployment with a model behind the seam writes its
own and points `PROFILE_PATH` and `inference.profile` at that instead.

| profile | reaches | what it is for |
| --- | --- | --- |
| `baseline:inference` | Stop, Abstain, Refer | reading a record and reporting, creating no work |
| `ladder:inference` | those three and Propose | turning a loop, by asking for the same run with one value raised |

`outcomes.py` holds the record's words for how a step ended and the one
judgement on them, because both profiles have to answer the same first
question before they answer anything of their own.

## What the advisory one concludes

Three of the four, and never the fourth.

```
    any step broken, or an engine that aborted or failed  ->  Refer
    the execution ended with steps it never reached       ->  Refer
    steps not reached and the execution still open        ->  Abstain
    every step done, engines clean, an objective given    ->  Stop
    anything else                                         ->  Abstain
```

It never proposes, so nothing it decides can become work at a beamline.
That is a property of this file rather than a limit of the seam, and
`ladder.py` beside it is the demonstration.

## What the proposing one concludes

The same first three rules, then a ladder: a clean run below a ceiling is
answered by proposing the same operation with one parameter doubled, and a
run at the ceiling is the objective met.

```
    the rung is already at the ceiling  ->  Stop
    otherwise, after a clean run        ->  Propose, rung doubled
```

A proposal is a record and nothing more. Turning one into work takes a
second act by somebody else, who states the beamline and the devices it
may drive, and those are refused unless a standing authorization already
covers them. So this cannot run anything by itself.

## Why it is here and not in the package

The package has three places a module can sit and this fits none of them.
`thinker.adapters` is one module per thing being spoken to, and a table of
rules speaks to nothing. The core is what a case is and what a conclusion
is, and is deliberately the part that holds no opinion about which
conclusion to reach. Putting a decider in either would be claiming it
belongs there.

So it ships beside the code rather than inside it, which is also what it
is: a deployment artifact, the simplest possible instance of the thing a
site writes.

## Why it is here and not in the tree that holds the other projects

Because this repository has to run on its own. A thinker whose only
runnable thinking lived in a sibling directory would ship something that
cannot be started from its own checkout, and the first person to find out
would be whoever installed it.

## What it is for, beyond starting

It is the baseline anything else is measured against. A profile with a
model behind it is better or worse than something, and without this there
is nothing to be better than.
