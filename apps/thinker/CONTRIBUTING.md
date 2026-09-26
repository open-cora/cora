# Contributing

The thinker is a personal research repository: it reads one execution back out
of the keeper and advises what to run next. It is public so the work can be
read, cited, and learned from, not because it is soliciting contributions.

## Where the code is developed

**This repository is what you deploy, install and cite.** Development happens
in [open-cora/cora](https://github.com/open-cora/cora), a tree holding this
project, the keeper it talks to and its sibling clients side by side, and this
repository is extracted from `apps/thinker` with `git subtree`, so the history
here is the real history rather than a squashed import.

That matters for one practical reason: a change merged here would be
overwritten by the next publish. Open an issue, or fork, and say which of the
two trees you read. Everything below applies to a change made in either place.

## What is welcome

- **Questions and corrections.** If a document states something false, a
  convention contradicts the code, or a guarantee is claimed that nothing
  provides, please open an issue. That class of defect is the one this
  project most wants reported.
- **A provider adapter.** `Inference` is one verb with no configuration, and a
  deployment names something that builds one. There is no such adapter in this
  repository on purpose. If you write one and the seam does not fit, the seam
  is wrong and that is worth an issue.
- **An argument that a conclusion is missing.** Four arms, and the case for
  each is written down in `conclusions.py`. A fifth needs an argument that it
  is a different answer to a different question rather than a shade of one
  already there.

## What is unlikely to be merged

- **Drive-by code pull requests.** The architecture is deliberate and most of
  it is documented in [docs/](docs/index.md). A change that reads as an
  improvement in isolation often violates a rule written down somewhere else,
  and reviewing that costs more than the change saves.
- **Dependency bumps and formatting changes.** These are handled in bulk.
- **Anything that crosses the split.** The core forms a conclusion and knows no
  outside system; the adapters know one each. An import that crosses that line
  works perfectly and makes an HTTP library a hard dependency of deciding what
  to run next.
- **A confidence, a score or a self-evaluation on a conclusion.** A thinker
  rating its own answer produces a number that reads as measurement and is
  assertion. This is the one refusal the project will not trade away.

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
3. **A case joins by id, never by position.** Both lists arrive in the
   procedure's order today, so a positional join passes the whole suite and
   mis-pairs every step after the first insertion. The test that would catch
   it reverses one of the lists, and a change to the pairing has to keep it.

Commits follow Conventional Commits with a scope; the subject says what and
the body says why.

## Relationship to the keeper

This is a client of [the keeper](https://github.com/open-cora/keeper) and not
a part of it. The dependency arrow points one way: a thinker dials the keeper
and the keeper never dials back. That is the arrangement every client in this
tree has, and [docs/thinking.md](docs/thinking.md) says what it costs.

There is no shared package. What binds the two is prose, in
[docs/client-contract.md](docs/client-contract.md): three routes, and the key
an execution's steps join to a procedure's on. Nothing in the keeper changed to
make this project work, which is the strongest statement available about how
much of the contract is already written down.

A patch here does not reach the keeper, and vice versa.

## License

Contributions are accepted under the [Apache-2.0](LICENSE) license of the
project.
