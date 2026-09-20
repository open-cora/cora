# Bluesky adapter spike

**This is not production code and nothing in `apps/api` depends on it.**
Read [FINDINGS.md](FINDINGS.md) first; the findings are the deliverable and
the scripts are only how they were obtained.

## Why it exists

Execution's write model was finished for the reported path, and the next
step was either the read side or an adapter. Those two are entangled:
`docs/bounded-contexts/execution.md` argues that the adapter is the right
place to decide a run's natural key, "because it is the first thing that
knows what the natural key actually is", and the unique index that would
close the duplicate-record gap is permanent once it ships.

So rather than guess the key and live with it, this drives a real
RunEngine into the real HTTP surface and reports what actually happens.

## Why it lives outside `apps/api`

Nothing here is covered by ruff, pyright, tach, pytest or any CI lane. All
of those are invoked with explicit paths from `apps/api`, so a directory at
the repo root is invisible to them. That is deliberate: code that has to
satisfy the architecture fitness suite is a landing, not a spike, and the
value of a spike is being able to write it fast and throw it away.

The precedent is `infra/atlas/scripts/tests/`, which is also Python outside
`apps/api` borrowing its virtualenv.

Bluesky is pulled in per invocation rather than added to
`apps/api/pyproject.toml`, so there is no dependency, no lockfile churn and
no CI lane touched. The Makefile already does this for the docs toolchain.

## Running it

Two halves, and the split is the point: `collect.py` needs no AROC at all,
so the Bluesky questions get answered before any integration code runs.

```sh
# From the repository root.

# 1. Drive a real RunEngine through seven scenarios, write documents.json.
uv run --project apps/api --with bluesky==1.15.1 --with ophyd \
    python spikes/bluesky_adapter/collect.py

# 2. Feed those documents into AROC over in-process HTTP and report.
uv run --project apps/api python spikes/bluesky_adapter/replay.py
```

`ophyd` is only needed for the one scenario that uses a stock plan with a
simulated detector, which is the only way to get a realistic `plan_args`.
Without it that scenario reports itself skipped and the rest still runs.

Step 2 needs no database and no server. `APP_ENV=test` boots the whole
application with in-memory adapters and `AllowAllAuthorize`, so an
unauthenticated caller runs as the system principal.

## What is here

| File | What it is |
| --- | --- |
| `FINDINGS.md` | The deliverable. Read this. |
| `collect.py` | Seven RunEngine scenarios, all three interruption channels armed. |
| `documents.json` | Captured output. Committed, because it is the evidence. |
| `replay.py` | A naive adapter driving AROC, plus two demonstrations of what breaks. |

## Why this is not deleted

This section used to say the directory goes when the real adapter lands.
The adapter landed, the deletion was attempted, and it was wrong three
times over. What it turned out to be is written here so nobody tries a
fourth time.

**`collect.py` is the only thing that can write the fixture.** The suite
asserts against `apps/reporter/tests/documents.json`, and that file is this
script's output. It cannot move next to the file it writes: the reporter
depends on three packages and none of them is bluesky or ophyd, and pyright
runs over `apps/reporter/tests` on every build. Outside both apps is the
only place it can live.

**The findings are cited from code that still runs.** The grant list in `apps/reporter/README.md` is section 5 of
FINDINGS, and `session.py` and `wire.py` cite the sibling spike for why
the seam sits where it does. A test
docstring pointing at recorded evidence for a rule it enforces is the
pattern working. Deleting the evidence because the experiment finished is
tearing a page out of the notebook.

So this is permanent, and the useful instruction is the opposite one:
**refresh it.** Re-run `collect.py` against a newer engine and the
capture is overwritten. The diff will be mostly noise, because ids and
timestamps change every run, and that is not what to read. What to read
is whether the suite still passes: the assertions are written against the
structural claims rather than the bytes, so a engine that changed one
of them turns a test red with a message naming it.
