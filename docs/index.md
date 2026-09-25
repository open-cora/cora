# CORA

One development tree holding four projects that ship apart. This site covers
what they are and how a request reaches hardware and comes back as a record.
Each project documents itself on its own site.

## The four

| Project | Does | Site |
| --- | --- | --- |
| **keeper** | Records what was proposed, run and produced | [open-cora/keeper](https://github.com/open-cora/keeper) |
| **conductor** | Walks a procedure across a beamline, one step at a time | [open-cora/conductor](https://github.com/open-cora/conductor) |
| **reporter** | Reports what an acquisition engine did | [open-cora/reporter](https://github.com/open-cora/reporter) |
| **thinker** | Proposes what to run next | [open-cora/thinker](https://github.com/open-cora/thinker) |

## How a step reaches hardware and comes back

```
   an actor proposes            ->  keeper       Counsel takes a proposal
   a procedure is composed      ->  keeper       Execution holds plans and steps
   the execution is dispatched  ->  keeper       named for one beamline

   a conductor asks what is waiting for its beamline
   it claims one execution, and the records each step names
   it drives a step through a seam a deployment installed
   it reports the outcome as the step ends          ->  keeper

   an engine publishes documents about the run
   a reporter translates them into step reports     ->  keeper
   and says where the data landed                   ->  keeper  Custody
```

Every arrow points the same way. A conductor dials the keeper and the keeper
never dials back, and so does a reporter. That is measured rather than
preferred: a survey of the beamlines this is pointed at found each one reaching
a central host and not the reverse, and it stays that shape even where the
reverse is reachable, because the alternative is an inbound port and a second
credential at every beamline.

## Why one tree

The four share a chassis and a set of conventions, and a change to either
touches more than one of them at once. Half the commits in the week this tree
was restructured did. Four repositories would make each of those a set of
coordinated pull requests that cannot land together, and would leave the
end-to-end path, dispatch through hardware and back, with no repository able to
hold a test for it.

So the work happens here and the four public repositories are **published
mirrors**, each a complete repository extracted from `apps/<name>` with its
history intact. They are for reading, citing and forking. A patch is welcome as
an issue or a fork; it lands here and arrives there on the next publish.

## What binds them

No shared package, on purpose. A conductor and a reporter import nothing from
the keeper and nothing from each other. What joins them is prose, in each
project's own client-contract page, plus two metadata keys that each side pins
to literals in a test of its own, so renaming one turns the other red.

## Where the facility is described

[`beamlines/`](beamlines/2-bm.md) holds what a running keeper has to be told
about a beamline it serves: the devices, their addresses, and the one rule on a
device reference. It sits at this level rather than inside any one project
because the conductor drives the motors it names and the reporter hears about
the detectors.
