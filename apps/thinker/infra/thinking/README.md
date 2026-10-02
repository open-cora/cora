# The thinking this repository ships

`inference.profile` names something importable that hands back whatever
concludes. Until this directory existed there was nothing here to name, so
an installed thinker had no way to start: the entrypoint imports the
profile before it reads anything, and a path naming nothing stops it there.

`baseline.py` is that something. It is the reference, not the only one: a
deployment with a model behind the seam writes its own and points
`PROFILE_PATH` and `inference.profile` at that instead.

## What it concludes

Three of the four, and never the fourth.

```
    any step broken, or an engine that aborted or failed  ->  Refer
    the execution ended with steps it never reached       ->  Refer
    steps not reached and the execution still open        ->  Abstain
    every step done, engines clean, an objective given    ->  Stop
    anything else                                         ->  Abstain
```

It never proposes, so nothing it decides can become work at a beamline.
That is a property of this file rather than a limit of the seam.

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
