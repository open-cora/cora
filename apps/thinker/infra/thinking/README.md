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
| `ladder:inference` | those three and Propose | turning a loop deterministically, by raising one value |
| `argo:inference` | those four | asking a model through the gateway this facility runs |

`outcomes.py` holds the record's words for how a step ended and the one
judgement on them, because every profile has to answer the same first
question before it answers anything of its own.

Going back to the record for what a case does not carry is the `Looking`
seam, handed to every profile by the entrypoint. It used to be a module
here that loaded the configuration a second time and built its own
client, which is a second credential path for a capability the service
already had.

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

## What the gateway profile does differently

It is handed the record and asked what to do next, where the ladder knows
one parameter and one ceiling. It is the thing the ladder exists to be
measured against.

**It does not ask the model whether the run went wrong.** The record holds
two claims about how each step ended and `outcomes` already reads them, so
that is a lookup, not a judgement. A broken step or a failed engine is
referred before a prompt is built, which also means a gateway that is down
or misconfigured cannot turn a failed run into a request for more of it.

**It believes only a parse, and that is a safety mechanism rather than
tidiness.** The gateway reports failures the way it reports answers. Both
of these came back as HTTP 200 with a body in the ordinary shape:

```
    an unauthorized username   role assistant, with usage and a stop
                               reason, content reading ACCESS DENIED
    a wrongly built request    the complaint sitting in the field an
                               answer would have been in
```

Neither is distinguishable from an answer by status, and the first is not
distinguishable by shape. Believing either writes a conclusion onto an
inquiry that nothing concluded. So the answer has to be exactly one JSON
object carrying one of four known words, and everything else raises, which
stops the thinking without writing anything. Both bodies above are
fixtures in the suite.

**Its settings come from a file the unit points at**, not from the
thinker's configuration, which holds what a thinker is rather than what a
model is. Write `~/.config/cora/thinking.env` and the installer picks it
up, the way a beamline's EPICS addressing is picked up next door:

```sh
CORA_ARGO_URL=https://apps.inside.anl.gov/argoapi/api/v1/resource/chat/
CORA_ARGO_USER=svccora
CORA_ARGO_MODEL=gpt4o
```

The keeper token is not among them. The unit is world readable in a shared
home; the token is at mode 600 in the configuration, and what the unit
passes is the path to it.
