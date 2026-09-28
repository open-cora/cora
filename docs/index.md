# CORA

One development tree holding four projects that ship apart. This site covers
what they are and how a request reaches hardware and comes back as a record.
Each project documents itself on its own site.

**This tree is for development. The four published repositories are for
release, deployment, install and citation.** The projects run in different
places, so each is installed on its own, versioned on its own and cited on its
own. Nothing is deployed from here.

## The four

| Project | Does | Site |
| --- | --- | --- |
| **keeper** | Holds the record, and who may add to it | [open-cora/keeper](https://github.com/open-cora/keeper) |
| **conductor** | Runs the work at the beamline | [open-cora/conductor](https://github.com/open-cora/conductor) |
| **reporter** | Reports what happened, and where the data went | [open-cora/reporter](https://github.com/open-cora/reporter) |
| **thinker** | Suggests what to run next | [open-cora/thinker](https://github.com/open-cora/thinker) |

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

   somebody invokes a thinker on that execution
   it reads the procedure and the record together   <-  keeper
   it concludes one of four things
   and proposes the next run if that is the one     ->  keeper  Counsel
```

Every arrow points the same way. A conductor dials the keeper and the keeper
never dials back, and so do a reporter and a thinker. That is measured rather
than preferred: a survey of the beamlines this is pointed at found each one
reaching a central host and not the reverse, and it stays that shape even
where the reverse is reachable, because the alternative is an inbound port and
a second credential at every beamline.

## Why one tree

The four share a chassis and a set of conventions, and a change to either
touches more than one of them at once. Renaming a shared rule, adding a lane,
correcting a convention page: each is one edit here and a set of coordinated
pull requests across four repositories that could not land together.

The end-to-end path is the sharper half. A dispatch reaches hardware through a
conductor and comes back as a record through a reporter, so a test of it has to
see three projects at once. Split four ways, no repository can hold that test,
and it is the path most worth testing.

So the work happens here and the four public repositories are **mirrors**, each
a complete repository extracted from `apps/<name>` with its history intact.
They are what a deployment installs and what a paper cites. A patch is welcome
as an issue or a fork; it lands here and reaches them on the next publish.

## What binds them

No shared package, on purpose. A conductor, a reporter and a thinker import
nothing from the keeper and nothing from each other. What joins them is prose,
in each project's own client-contract page, plus two metadata keys that the
conductor and the reporter each pin to literals in a test of its own, so
renaming one turns the other red.

A thinker is not party to those keys, because it never speaks to an engine.
What binds it is narrower and needed no change to the keeper: two routes it
reads, one it writes, and the key an execution's steps join to a procedure's
on.

## Where the facility is described

[`beamlines/`](beamlines/2-bm.md) holds what a running keeper has to be told
about a beamline it serves: the devices, their addresses, and the one rule on a
device reference. It sits at this level rather than inside any one project
because the conductor drives the motors it names and the reporter hears about
the detectors.
