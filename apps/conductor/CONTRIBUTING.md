# Contributing

The conductor is a personal research repository: it walks a
procedure across a beamline, one step at a time. It is public so the work can be read, cited, and learned from, not
because it is soliciting contributions.

## What is welcome

- **Questions and corrections.** If a document states something false, a
  convention contradicts the code, or a guarantee is claimed that nothing
  provides, please open an issue. That class of defect is the one this
  project most wants reported.
- **A second control system..** Everything above `conductor.adapters` takes a seam
  shaped like the verbs it uses, so a Tango or a Modbus deployment should be
  an adapter rather than a rewrite. If you try one and it does not fit, the
  seam is wrong and that is worth an issue.

## What is unlikely to be merged

- **Drive-by code pull requests.** The architecture is deliberate and most of
  it is documented in [docs/](docs/index.md). A change that reads as an
  improvement in isolation often violates a rule written down somewhere else,
  and reviewing that costs more than the change saves.
- **Dependency bumps and formatting changes.** These are handled in bulk.
- **Anything that crosses the split.** The core composes a procedure and knows no outside
  system; the adapters know one each. An import that crosses that line works
  perfectly and makes a control library a hard dependency of composing a
  procedure.

If you want to build on this, fork it. That is the intended use.

## If you do send a change

Read [docs/conventions.md](docs/conventions.md) first. In short:

```bash
make install      # uv sync
make precommit    # install the hooks, including the pre-push pass
make lint typecheck
make test
```

Three things that are easy to get wrong here:

1. **Stage your files before trusting a green run.** Every structural and
   prose rule enumerates through `git ls-files`, so a file git has never seen
   is invisible to all of them. A green run on unstaged work means nothing.
2. **A new test must be able to fail.** Break the thing it names and watch it
   go red before you trust it. Several checks in this project's sibling trees
   were found to be testing nothing exactly this way.
3. **The Channel Access tests drive real motion. They serve a caproto
   soft IOC on the loopback, so they need no EPICS installation, and they
   take about eighty seconds. `make test-core` skips them; CI does not.**

Commits follow Conventional Commits with a scope; the subject says what and
the body says why.

## Relationship to the keeper

This is a client of [the keeper](https://github.com/open-cora/keeper) and not
a part of it. The dependency arrow points one way: a conductor dials the keeper and
the keeper never dials back. That is measured rather than preferred, and
[docs/conducting.md](docs/conducting.md) says why.

There is no shared package. What binds the two is prose, in
[docs/client-contract.md](docs/client-contract.md), plus two metadata keys
that each side pins to literals in a test of its own. That is the whole
contract, and it is written down in both repositories on purpose: a copy that
drifts is caught by the pins rather than by a reader.

A patch here does not reach the keeper, and vice versa.

## License

Contributions are accepted under the [Apache-2.0](LICENSE) license of the
project.
