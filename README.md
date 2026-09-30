# CORA

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)

One development tree holding four projects that ship apart. Together they take
a proposal, compose a procedure from it, walk that procedure across a beamline,
and record what was run and where the data went.

**This repository is where the work happens.** Each project lives under
`apps/` as a complete repository of its own, with its own lockfile, its own
gate and its own documentation site, and each is published to a repository of
its own.

**Those published repositories are what you release, deploy, install and
cite.** The projects run in different places: the keeper where the database
is, a conductor at a beamline, a reporter where an acquisition engine is, a
thinker wherever its thinking runs. Each is installed on its own, versioned
on its own and cited on its own. Nothing is deployed from here.

## Why these exist

Beamline software assumes somebody is watching. The person at the terminal
decides what to measure next, and their being there is what makes the decision
allowed and what makes it remembered.

Take the person away and three things go at once: the judgement about what to
run next, the authority that made it permitted, and the account of what was
actually done. Software that decides what to measure is now easy to come by.
The record of what that software was allowed to do, and what came of it, is
not, and without it an unattended run produces data nobody can defend
afterwards.

These four supply the second half. The judgement is a suggestion until
something with granted authority takes it up, what runs is driven by a part
that claims no opinion about the science, and what happened is filed by a part
that reads none of it. The split is the point: no one of them can both decide
and authorize.

## The four

| Project | Does | Published as |
| --- | --- | --- |
| [keeper](apps/keeper/) | Holds the record, and who may add to it | [open-cora/keeper](https://github.com/open-cora/keeper) |
| [conductor](apps/conductor/) | Runs the work at the beamline | [open-cora/conductor](https://github.com/open-cora/conductor) |
| [reporter](apps/reporter/) | Reports what happened, and where the data went | [open-cora/reporter](https://github.com/open-cora/reporter) |
| [thinker](apps/thinker/) | Suggests what to run next | [open-cora/thinker](https://github.com/open-cora/thinker) |

All four run, and the arrows between them all point one way: a client dials
the keeper and the keeper never dials back. The
[documentation home page](docs/index.md) draws the whole path and says why it
has that shape.

## Why one tree rather than four repositories

The projects share a chassis and a set of conventions, and a change to either
touches more than one of them at once. Renaming a shared rule, adding a lane,
correcting a convention page: each is one edit here and a set of coordinated
pull requests across four repositories that could not land together.

The end-to-end path is the other half, and the sharper one. A dispatch reaches
hardware through a conductor and comes back as a record through a reporter, so
a test of it has to see three projects at once. Split four ways, no repository
can hold that test, and it is the path most worth testing.

The published repositories are therefore **mirrors**, each extracted from
`apps/<name>` with `git subtree` so its history is the real history rather than
a squashed import. A change lands here and reaches them on the next publish.

Mirroring costs something and the cost is duplication. A mirror has to run its
own suite and build its own site standalone, so anything its tests read or its
site links has to be physically present in it: the licence, the Python pin, the
ignore rules, the conventions pages. What this tree buys is not one copy, it is
copies a test can prove identical, which is what
[tests/test_the_shared_root_files_are_identical.py](tests/test_the_shared_root_files_are_identical.py)
does for the four files that must never differ.

## On the name

CORA is this tree and the four projects in it. The name is older than that
arrangement: the chassis under `apps/keeper` was copied once from an earlier,
private tree that carried it first, and has been owned outright from that
point on. There is no shared package with that tree and no expectation that a
fix in one reaches the other.

It is mentioned once, here, and nowhere else. Two things with one name is a
confusion worth removing rather than repeating, so the pages in each project
say "the tree this chassis was copied from" and leave it unnamed. Nothing a
reader can reach depends on it.

## Quick start

Requires Python 3.13.12 (via uv), Docker (for the keeper's Postgres), and
[Atlas](https://atlasgo.io/) (for its schema migrations).

```bash
make install        # uv sync every app
make precommit      # install git hooks (one-time per clone)
make test           # every app's suite
make docs-build     # every site, strict
```

The keeper's database targets are delegated from here too:

```bash
make db-up          # start Postgres on host port 5433
make migrate-apply  # apply the schema
make dev            # API at http://localhost:8000, health at /health
```

`make help` lists the rest. Every target loops the apps or delegates to one of
them with `make -C`; this Makefile defines no lane of its own, so a lane has
one spelling whether it runs here or in a mirror.

## Layout

| Path | Contents |
| --- | --- |
| `apps/<name>/` | One complete repository each, published as a mirror |
| `beamlines/` | What a running keeper has to be told about a facility |
| `tests/` | The checks that range over more than one project |
| `docs/` | This site: what the projects are and how they fit |
| `Makefile` | Delegates to each app; defines nothing an app defines |
| `.github/workflows/` | Gates this tree; each app's workflow gates its mirror |

`beamlines/` sits at this level rather than inside any one project because the
conductor drives the motors it names and the reporter hears about the
detectors. It imports none of them.

`tests/` holds what no project can check alone: that every copy of a shared
file is identical, and the prose rules over everything outside `apps/`. A rule
that ranges over one project belongs to that project; one that ranges over
several, or over what belongs to none, belongs here.

## Documentation

One site per repository. This one says what the projects are and how a request
reaches hardware and comes back as a record; each project documents itself.
`make docs-build` builds all of them with `--strict`, which is the only thing
that fails a build on a broken cross-link.

## Contributing

These are research repositories, public to be read rather than to solicit
patches. Corrections and questions are welcome; see
[CONTRIBUTING.md](CONTRIBUTING.md).

## License

Apache-2.0. See [LICENSE](LICENSE).
