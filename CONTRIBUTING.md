# Contributing

CORA is a personal research tree. It is public so the work can be read, cited,
and learned from, not because it is soliciting contributions.

## This is where the code is developed

The four public project repositories are **published mirrors**, extracted from
`apps/<name>` with `git subtree`. A change merged into one of them would be
overwritten by the next publish, so this is the tree to read and the tree to
fork.

A mirror is a complete repository and runs standalone, so working in one is
fine. What it cannot hold is a change touching more than one project, or a test
of the path that runs through several of them, which is the reason this tree
exists.

## What is welcome

- **Questions and corrections.** If a document states something false, a
  convention contradicts the code, or a guarantee is claimed that nothing
  provides, please open an issue. That class of defect is the one this project
  most wants reported. Issues on a mirror are read too.
- **Discussion of the modeling.** The keeper exists to try domain designs on a
  settled chassis, and the clients exist to find out what such a design costs
  at a beamline. If you have modeled something similar and reached a different
  answer, that is interesting and worth an issue.

## What is unlikely to be merged

- **Drive-by code pull requests.** The architecture is deliberate and most of
  it is written down. A change that reads as an improvement in isolation often
  violates a rule recorded somewhere else, and reviewing that costs more than
  the change saves.
- **Dependency bumps and formatting changes.** These are handled in bulk.
- **New bounded contexts.** Those are the whole point of the project and are
  not delegated.

If you want to build on this, fork it. That is the intended use.

## If you do send a change

Each project states its own workflow; read the `CONTRIBUTING.md` in the
directory you are touching. Across the tree:

```bash
make install                 # uv sync every app
make precommit               # install the hooks, including the pre-push pass
make lint typecheck test     # every app
make docs-build              # every site, strict
```

Four things that are easy to get wrong here, and the first two are the ones
that have actually cost time:

1. **Stage your files before trusting a green run.** Every structural and
   prose rule enumerates through `git ls-files`, so a file git has never seen
   is invisible to all of them. A green run on unstaged work means nothing.
2. **A new test must be able to fail.** Break the thing it names and watch it
   go red before you trust it. Several checks here were found to be testing
   nothing exactly this way, including a lint hook whose file pattern named a
   directory that had been renamed, so it matched no file and reported success
   on every commit.
3. **Keep each project self-contained.** A mirror runs its own suite and builds
   its own site with nothing beside it. A rule that reaches a sibling directory
   passes here and fails there, and only a subtree split into a fresh clone
   catches it. [CLAUDE.md](CLAUDE.md) spells that check out.
4. **Put a lane in the app's Makefile, not the root's.** The root delegates on
   purpose. A lane defined at the root is a copy that nothing compares against
   the one the mirror runs.

Commits follow Conventional Commits with a scope; the subject says what and the
body says why. A commit may touch several projects, which is what this tree is
for.

## License

Contributions are accepted under the [Apache-2.0](LICENSE) license of the
project.
