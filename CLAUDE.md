# Repo guidance

This file is read by Claude Code (and other agents that respect `CLAUDE.md`).
Keep it as a pointer file, not a long doc.

## What this tree is

CORA: one development tree holding projects that ship apart. Each directory
under `apps/` is a complete repository with its own lockfile, its own gate and
its own site, and each is published as a mirror with `git subtree`. The work
happens here; the public repositories are extracted from here.

Per-project guidance lives with the project and is what governs a change to it:

- [apps/keeper/CLAUDE.md](apps/keeper/CLAUDE.md)
- [apps/conductor/CLAUDE.md](apps/conductor/CLAUDE.md)
- [apps/reporter/CLAUDE.md](apps/reporter/CLAUDE.md)
- [apps/thinker/CLAUDE.md](apps/thinker/CLAUDE.md)

Read the one for the project you are editing. This file carries only what holds
everywhere and what is true of the tree rather than of any project in it.

## The rule the layout exists to serve

**Every `apps/<name>` has to be a complete repository on its own.** A mirror
runs its own suite and builds its own site with nothing beside it, so anything
a project's tests read or its site links has to be inside its directory.

That is why the conventions pages, the licence, the Python pin and the ignore
rules exist four times rather than once. The duplication is the price of the
mirrors, and it is paid on purpose. What keeps it honest is that a test proves
the copies identical, not that somebody remembers to update them.

A change that makes a project reach outside its own directory breaks the
mirror, and the suite will not tell you: it passes here because the sibling
happens to sit next door. The check that catches it is a subtree split into a
fresh clone, and it is worth running after anything structural:

```bash
git subtree split --prefix=apps/<name> -b probe/<name>
git clone --branch probe/<name> . /tmp/probe-<name>
cd /tmp/probe-<name> && uv sync --locked --all-extras
make lint && make typecheck && make docs-build && uv run pytest -q
```

## Lanes

The root `Makefile` and `.github/workflows/ci.yml` delegate and define nothing
an app defines. A lane belongs in the app's own `Makefile`, so it has one
spelling whether it runs here or in the mirror. Adding a lane here instead
creates a copy that nothing compares.

```bash
make lint typecheck test    # the tree's own lane, then every app
make -C apps/<name> test    # one app
make tree-test              # only what belongs to no project
make docs-build             # every site, strict
```

## Hard rules carried into every change, in every project

Each project states these in its own `CLAUDE.md` and enforces them with its own
tests, because a mirror has to carry its own rules. They do not differ.

- No phase, iteration or audit tags in source, tests or documentation: a plan
  coordinate, an iteration label, a dated audit tag, a numbered review finding.
  Git log is the right home.
- No emoji anywhere in source: comments, docstrings, log strings, error
  messages, `Field(description=...)`.
- No em dashes in user-facing prose; use commas, colons, or rephrase.
- Default to no `#` comments. Add one only when the WHY is non-obvious.
- Test names carry scenarios (`test_<subject>_<scenario>_<expectation>`);
  per-test docstrings stay rare.
- A docstring may not name a symbol or a file that does not exist. Backticks
  mean "this is a symbol"; use a plain word when you mean a word.

Two more that are about how the tests are written rather than what they say:

- **Stage new files before trusting a green run.** Every structural and prose
  rule in every project enumerates through `git ls-files`, so a file git has
  never seen is invisible to all of them.
- **A new test must be able to fail.** Break the thing it names and watch it go
  red before trusting it. Several checks in this tree were found to be testing
  nothing exactly this way, and one of them was a filter that had stopped
  matching any file at all.

## What is not in any project

`beamlines/` describes a facility and belongs to none of them: the conductor
drives the motors it names and the reporter hears about the detectors. The root
`docs/` is the same, covering how the projects fit rather than any one of them.

`tests/` is the tier that checks them, plus the one rule no project can hold:
that every copy of a shared file is identical. Its enumerators exclude `apps/`
on purpose, because each project scans itself and a second scan from here would
let a project's own copy of a rule rot behind this one. A check that ranges over
more than one project goes here; a check about one project goes in that project.

## Memory hygiene

Auto-memory grows monotonically without a forcing function. These rules curb
drift between sessions. They apply to this tree's Claude auto-memory directory:
`~/.claude/projects/<repo-path-slug>/memory/`, where `<repo-path-slug>` is the
repository's absolute path with `/` replaced by `-` (it differs per machine).

- A new memo's one-line pointer goes in `MEMORY.md` under the shelf that fits:
  a durable convention, principle, or pattern, a user fact, or feedback.
- Before creating a new memo, grep the index for the topic; prefer edit-in-place
  over a new file.
- Mutable status does not belong in index descriptions; the index carries the
  durable claim, the file carries the status.
- Any index description containing a count or a date older than 7 days requires
  a Read of the underlying file before quoting in chat.
- Memo files over ~300 lines: split into 2-3 sibling files linked from the first.

One directory serves the whole tree, because the slug is the checkout's path
and there is one checkout. A memo about one project should say which.

## Commits

One-line subject, body explains WHY. Recent commits set the tone; read
`git log --oneline -10`.

A commit may touch more than one project, and that is the reason this tree is
one tree. Keep such a commit to one change described one way rather than
splitting it per directory.
