# Repo guidance

This file is read by Claude Code (and other agents that respect `CLAUDE.md`).
Keep it as a pointer file, not a long doc; the real conventions live in
`docs/`.

## What this repo is

A conductor walks a procedure across a beamline, one step at a time. It asks
the keeper what is waiting for it, claims the hardware a step names, drives
that step through a seam, and reports how the step ended.

It is a client of the keeper and not a part of it. The dependency arrow
points one way: a conductor dials the keeper and the keeper never dials
back. There is no shared package between them, and the wire contract is
prose plus two metadata keys pinned to literals on each side.

The chassis conventions came from the keeper's tree and are owned outright
from that point on. A fix here does not reach there.

## Conventions

- **Naming, documentation, commits, branch flow, test names**: [docs/conventions.md](docs/conventions.md)
- **Docstring + comment + test-doc style specifically**: [docs/conventions.md#documentation](docs/conventions.md#documentation)
- **What the keeper promises a client, and what it does not**: [docs/client-contract.md](docs/client-contract.md)
- **What conducting is and how a walk goes**: [docs/conducting.md](docs/conducting.md)
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
| `tests/test_test_names_carry_outcome.py` | A test name states a property |
| `tests/test_the_core_names_no_seam.py` | The core imports no adapter |
| `tests/test_the_record_outlives_the_walk.py` | A walk reports what it did |

Each enumerates through `git ls-files`, so **a file git has never seen is
invisible to every one of them**. Stage new files before trusting a green
run.

## Two things that are easy to get wrong

**A new test must be able to fail.** Break the thing it names and watch it go
red before trusting it. Several checks in this project's sibling trees were
found to be testing nothing exactly this way.

**The Channel Access tests drive real motion.** They serve a caproto soft IOC
on the loopback, so they need no EPICS installation, and they take about
eighty seconds. `make test-core` skips the motion; CI runs everything.

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
