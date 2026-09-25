# CORA

[![License: Apache-2.0](https://img.shields.io/badge/license-Apache--2.0-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/downloads/release/python-3130/)

One development tree holding four projects that ship apart. Together they take
a proposal, compose a procedure from it, walk that procedure across a beamline,
and record what was run and where the data went.

Each project is a complete repository living under `apps/`, with its own
lockfile, its own gate and its own documentation site, and each is published as
a mirror. The work happens here.

## The four

| Project | Does | Published as |
| --- | --- | --- |
| [keeper](apps/keeper/) | Records what was proposed, run and produced | [open-cora/keeper](https://github.com/open-cora/keeper) |
| [conductor](apps/conductor/) | Walks a procedure across a beamline, one step at a time | [open-cora/conductor](https://github.com/open-cora/conductor) |
| [reporter](apps/reporter/) | Relays what an acquisition engine did | [open-cora/reporter](https://github.com/open-cora/reporter) |
| thinker | Proposes what to run next | [open-cora/thinker](https://github.com/open-cora/thinker) |

The thinker has no code yet. The other three run, and the arrows between them
all point one way: a client dials the keeper and the keeper never dials back.
The [documentation home page](docs/index.md) draws the whole path and says why
it has that shape.

## Why one tree rather than four repositories

The projects share a chassis and a set of conventions, and a change to either
touches more than one of them at once. Half the commits in the week this tree
was restructured did. Four repositories would make each of those a set of
coordinated pull requests that cannot land together, and would leave the
end-to-end path, dispatch through hardware and back, with no repository able to
hold a test for it.

The public repositories are therefore **published mirrors**, each extracted
from `apps/<name>` with `git subtree` so its history is the real history. They
are for reading, citing and forking. A patch lands here and arrives there on
the next publish.

Mirroring costs something and the cost is duplication. A mirror has to run its
own suite and build its own site standalone, so anything its tests read or its
site links has to be physically present in it: the licence, the Python pin, the
ignore rules, the conventions pages. What this tree buys is not one copy, it is
copies a test can prove identical, which is what
`apps/keeper/tests/architecture/test_the_shared_root_files_are_identical.py`
does for the four files that must never differ.

## On the name

The name is reused, and knowing that saves a reader one confusion. The chassis
under `apps/keeper` was copied once from an earlier, private tree that also
carried this name, and is owned outright from that point on. There is no shared
package with it and no expectation that a fix in one reaches the other. That
project is not this one, and nothing here depends on it.

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

`tests/` holds what no project can check alone: that the four copies of each
shared file are identical, and the prose rules over everything outside
`apps/`. Those two directories were in no lane at all until this tier existed,
so nothing linted them, nothing typechecked them, and three passes of prose
fixes during the restructure kept finding more in `beamlines/` because no rule
reached it.

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
