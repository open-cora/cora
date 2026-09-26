# Repo guidance

This file is read by Claude Code (and other agents that respect `CLAUDE.md`).
Keep it as a pointer file, not a long doc; the real conventions live in
`docs/`.

## What this repo is

A thinker reads one execution back out of the keeper, pairs what the procedure
asked for with what became of it, hands that whole case to whatever does the
thinking, and writes the answer down if the answer is a proposal.

It is invoked, not autonomous. Nothing dispatches work to a thinker and nothing
in this tree reacts to an event by writing another one, so a thinker is started
with an execution id in hand, thinks once, and exits.

It is a client of the keeper and not a part of it. The dependency arrow points
one way: a thinker dials the keeper and the keeper never dials back. There is no
shared package between them, and no change to the keeper was needed to make this
work: it reads two routes that already existed and writes one that already
existed.

The chassis conventions came from a sibling's tree and are owned outright from
that point on. A fix here does not reach there.

## Conventions

- **Naming, documentation, commits, branch flow, test names**: [docs/conventions.md](docs/conventions.md)
- **Docstring + comment + test-doc style specifically**: [docs/conventions.md#documentation](docs/conventions.md#documentation)
- **What the keeper promises a client, and what it does not**: [docs/client-contract.md](docs/client-contract.md)
- **What one thinking is and what it may conclude**: [docs/thinking.md](docs/thinking.md)
- **The objects, one invocation drawn, who decides what**: [docs/architecture.md](docs/architecture.md)
- **Glossary**: [docs/glossary.md](docs/glossary.md)

## Hard rules carried into every change

- No phase, iteration or audit tags in source: a plan coordinate, an
  iteration label, a dated audit tag, a numbered review finding. Git log is
  the right home, and `tests/test_no_phase_markers.py` spells every shape it
  refuses.
- No emoji anywhere in source: comments, docstrings, log strings, error messages.
- No em dashes in user-facing prose; use commas, colons, or rephrase.
- Default to no `#` comments. Add one only when the WHY is non-obvious.
- Test names carry scenarios (`test_<subject>_<scenario>_<expectation>`); per-test docstrings stay rare.
- A docstring may not name a symbol or a file that does not exist. Backticks mean "this is a symbol"; use a plain word when you mean a word.

## The rules that are actually enforced

Unusually for a package this size, every rule above except the comment
default is a test. They live beside the suite rather than in a tier of their
own, because there is one tier:

| File | Holds |
| --- | --- |
| `tests/test_no_em_dashes.py` | No em or en dash in source or prose |
| `tests/test_no_emoji.py` | No emoji in source or prose |
| `tests/test_no_phase_markers.py` | No plan coordinate or finding code |
| `tests/test_docstring_references_resolve.py` | Every backticked name and cited path resolves |
| `tests/test_every_relative_link_resolves.py` | Every relative link in prose points at a file |
| `tests/test_test_names_carry_outcome.py` | A test name states a property |
| `tests/test_the_core_names_no_seam.py` | The core imports no adapter |
| `tests/test_the_declared_versions_agree.py` | The two declared versions match |

Each enumerates through `git ls-files`, so **a file git has never seen is
invisible to every one of them**. Stage new files before trusting a green
run.

## Three things that are easy to get wrong

**A new test must be able to fail.** Break the thing it names and watch it go
red before trusting it. Several checks in this project's sibling trees were
found to be testing nothing exactly this way.

**A case joins by id and never by position.** An execution step's
`procedure_step_id` pairs with a procedure step's `step_id`, which is what the
keeper's own routes say to do. Both lists arrive in the procedure's order today,
so a positional join would pass every test that exists and would mis-pair every
step after the first insertion. The join lives in `assemble` and not in any
adapter, so that every implementation of the reading seam goes through it
rather than being trusted to repeat it. Both the join and what position
would do instead are drawn on [docs/architecture.md](docs/architecture.md).

**A failure is never a conclusion.** Nothing here catches a keeper that could
not be reached or a provider that raised. Converting either into `Abstain` would
report a thinker that looked and found nothing, and would be a thinker that did
not look.

## Memory hygiene

Auto-memory grows monotonically without a forcing function. These rules curb
drift between sessions. They apply to this repo's Claude auto-memory
directory: `~/.claude/projects/<repo-path-slug>/memory/`, where
`<repo-path-slug>` is the repository's absolute path with `/` replaced by `-`
(it differs per machine).

- A new memo's one-line pointer goes in `MEMORY.md` under the shelf that fits: a durable convention, principle, or pattern, a user fact, or feedback.
- Before creating a new memo, grep the index for the topic; prefer edit-in-place over a new file.
- Mutable status does not belong in index descriptions; the index carries the durable claim, the file carries the status.
- Any index description containing a count or a date older than 7 days requires a Read of the underlying file before quoting in chat.
- Memo files over ~300 lines: split into 2-3 sibling files linked from the first.

## Commits

One-line subject, body explains WHY. Recent commits set the tone; read
`git log --oneline -10`.
