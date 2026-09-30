# CORA

One development tree holding four projects that ship apart. This site is for
working in the tree: what the four are, how a request reaches hardware and
comes back as a record, and what the layout asks of a change. Each project
documents itself on its own site, and those are the pages written for somebody
who wants to install one.

**This tree is for development. The four published repositories are for
release, deployment, install and citation.** The projects run in different
places, so each is installed on its own, versioned on its own and cited on its
own. Nothing is deployed from here.

## The four

| Project | Does | Published as |
| --- | --- | --- |
| **keeper** | Holds the record, and who may add to it | [open-cora/keeper](https://github.com/open-cora/keeper) |
| **conductor** | Runs the work at the beamline | [open-cora/conductor](https://github.com/open-cora/conductor) |
| **reporter** | Reports what happened, and where the data went | [open-cora/reporter](https://github.com/open-cora/reporter) |
| **thinker** | Suggests what to run next | [open-cora/thinker](https://github.com/open-cora/thinker) |

Each is a complete repository under `apps/`, with its own lockfile, its own
gate and its own site, published as a mirror with `git subtree` so its history
is the real history rather than a squashed import. They are developed together
because a change to the shared chassis or to a convention touches more than one
of them at once, and because the end-to-end path below is a test no single
repository could hold.

## The path a request takes

```
   an actor proposes            ->  keeper       Counsel takes a proposal
   a procedure is composed      ->  keeper       Execution holds operations and procedures
   the execution is dispatched  ->  keeper       named for one beamline

   a conductor asks what is waiting for its beamline
   it claims one execution, and the records each step names
   it drives a step through a seam a deployment installed
   it reports the outcome as the step ends          ->  keeper

   an engine publishes documents about the run
   a reporter translates them into step reports     ->  keeper
   and says where the data landed                   ->  keeper  Custody

   a thinker takes up a question about that execution
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

## What the four share, and what they do not

No shared package, on purpose. A conductor, a reporter and a thinker import
nothing from the keeper and nothing from each other. What joins them is prose,
in each project's own client-contract page, plus two metadata keys that the
conductor and the reporter each pin to literals in a test of its own, so
renaming one turns the other red.

A thinker is not party to those keys, because it never speaks to an engine.
What binds it is narrower and needed no change to the keeper: two routes it
reads, one it writes, and the key an execution's steps join to a procedure's
on.

## Working in this tree

Python 3.13.12 through uv, Docker for the keeper's Postgres, and
[Atlas](https://atlasgo.io/) for its schema migrations.

```bash
make install        # uv sync every app
make precommit      # install the git hooks, once per clone
make test           # this tier's checks, then every app's suite
make docs-build     # every site, strict
make publish        # push this tree, then each project to its mirror
```

`make help` lists the rest, including the keeper's database targets. A change
goes in the project it belongs to, under `apps/<name>`, and reaches the
published repository on the next publish. A lane belongs in that project's own
`Makefile`, so it has one spelling whether it runs here or in the mirror: the
root `Makefile` delegates and defines nothing an app defines.

**Every `apps/<name>` has to be a complete repository on its own.** A mirror
runs its own suite and builds its own site with nothing beside it, so anything
a project's tests read or its site links has to be physically present inside
that project. This is why the conventions pages, the licence, the Python pin
and the ignore rules exist four times rather than once, and why
[a test proves the copies identical](https://github.com/open-cora/cora/blob/main/tests/test_the_shared_root_files_are_identical.py)
rather than anyone being asked to remember.

A change that breaks that rule passes here, because the sibling it reached for
happens to sit next door. What catches it is a subtree split into a fresh
clone, which is worth running after anything structural:

```bash
git subtree split --prefix=apps/<name> -b probe/<name>
git clone --branch probe/<name> . /tmp/probe-<name>
cd /tmp/probe-<name> && uv sync --locked --all-extras
make lint && make typecheck && make docs-build && uv run pytest -q
```

What no project can check alone lives in `tests/` at the root: that every copy
of a shared file is identical, and the prose rules over everything outside
`apps/`.

## Where to go next

[Where each part runs](beamlines/index.md) says what runs where, who each part
is when it arrives, and what has not been proven yet. Beside it sits a page for
each beamline somebody has surveyed, which is now all four:
[2-BM](beamlines/2-bm.md), [7-BM](beamlines/7-bm.md),
[19-BM](beamlines/19-bm.md) and [32-ID](beamlines/32-id.md). The descriptors behind those pages live in `beamlines/` at
the root rather than inside any one project, because the conductor drives the
motors they name and the reporter hears about the detectors.

Each project's own site covers installing it, running it and how it is built.
These are research repositories, public to be read rather than to solicit
patches; corrections and questions are welcome, and
[CONTRIBUTING.md](https://github.com/open-cora/cora/blob/main/CONTRIBUTING.md)
says what is likely to land.
