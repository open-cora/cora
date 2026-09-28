# Store adapter spike

**This is not production code and nothing in `apps/keeper` depends on it.**
Read [FINDINGS.md](FINDINGS.md) first; the findings are the deliverable and
the scripts are only how they were obtained.

## Why it exists

The reported path for runs is nearly whole, and the next context is a small
one for output data: where the data a run produced ended up, and who is
keeping it. Two questions gate its first migration. What identifies a body
of data in the store, which the external reference has to carry and cannot
change afterwards. And when a reporter may ask, which decides whether the
record is a fact or a guess.

Both are questions about a real service rather than about the model, and
the sibling spike at `spikes/bluesky_adapter/` is the precedent for how
this project answers those: drive the real thing, print what happened, and
let the wire overrule the documentation. That spike changed the model twice
in ways reading could not have, so this one runs before the context is
written rather than after.

## Why it lives outside `apps/keeper`

Nothing here is covered by ruff, pyright, tach, pytest or any CI lane. All
of those are invoked with explicit paths from `apps/keeper`, so a directory at
the repo root is invisible to them. That is deliberate: code that has to
satisfy the architecture fitness suite is a landing, not a spike, and the
value of a spike is being able to write it fast and throw it away.

It is also the only place allowed to name the products involved.
`test_the_domain_names_no_product.py` reaches `src/aroc` and `docs` and
nothing else, for the reason its docstring gives: which engine and which
store a deployment runs are a deployment's facts, and a rule stated for one
reads as a rule derived from one.

That test had no category for a store when this spike was written, and it
has one now. The awkwardness this section used to flag was real and was
settled rather than waved through: the store's name is an ordinary English
adjective, so it is matched as a proper noun and left alone in lower case.
Extending the rule caught one line on its first run, a design precedent in
`infrastructure/auth/config.py` that had cited the store by name back when
nothing here kept data anywhere.

## Running it

Two halves, and the split is forced rather than chosen.

```sh
# From the repository root.

# 1. Drive a real engine into a real store through the writer a deployment
#    would use, and capture what the store reports. No AROC.
uv run --no-project --python 3.13 \
    --with 'tiled[server,client]' --with bluesky --with ophyd \
    python spikes/tiled_adapter/collect.py

# 2. Take that capture into the real HTTP surface and see what a record
#    could hold. No store.
uv run --project apps/keeper python spikes/tiled_adapter/resolve.py
```

Step 1 cannot use `--project apps/keeper`. The store's client drives its own
server through `starlette.testclient`, and `apps/keeper` pins `httpx2`
alongside `httpx` for its own test client; that code path picks up the
wrong one and refuses with a `TypeError` about the URL type. Step 2 needs
`apps/keeper` and must not have the store's client beside it. `nodes.json` is
the seam, which is also why the two halves answer cleanly separated
questions.

Step 2 needs no database and no server. `APP_ENV=test` boots the whole
application with in-memory adapters and `AllowAllAuthorize`, so an
unauthenticated caller runs as the system principal.

`ophyd` supplies the simulated detector, so the captured run has real
readings rather than an empty stream. Without it `collect.py` does not run
at all, which is the difference from the sibling spike, where the detector
was needed by one scenario out of seven.

## What is here

| File | What it is |
| --- | --- |
| `FINDINGS.md` | The deliverable. Read this. |
| `collect.py` | Four scenarios plus three probes: subscription order, address spellings, and where the bytes actually are. |
| `nodes.json` | Captured output, now at `apps/reporter/tests/nodes.json`, because the dataset leg asserts against it there. Written by `collect.py` and read by `resolve.py`. |
| `resolve.py` | The join into AROC, and every candidate key run through the real `Identifier`. |

`resolve.py` posts no dataset. It assembles the value that slice would be
handed and puts it through the value object the record inherits, which is
the part that can be wrong today and expensive to change later. It did
that before Custody existed and the answer has not changed since, which is
the useful thing about having asked it in this form.

## Why this is not deleted

This section used to say the directory goes when the real adapter lands.
The adapter landed, the deletion was attempted, and it was wrong three
times over. What it turned out to be is written here so nobody tries a
fourth time.

**`collect.py` is the only thing that can write the fixture.** The suite
asserts against `apps/reporter/tests/nodes.json`, and that file is this
script's output. It cannot move next to the file it writes: the reporter
depends on three packages and none of them is tiled, and pyright
runs over `apps/reporter/tests` on every build. Outside both apps is the
only place it can live.

**The findings are cited from code that still runs.** `src/reporter/stores.py` cites section 1 for why the
address is computed rather than read, the store-library ban in
`apps/reporter/tests/test_the_halves_stay_apart.py` cites it for why no store client is
imported, and `apps/reporter/README.md` cites section 7 for the grants. A test
docstring pointing at recorded evidence for a rule it enforces is the
pattern working. Deleting the evidence because the experiment finished is
tearing a page out of the notebook.

So this is permanent, and the useful instruction is the opposite one:
**refresh it.** Re-run `collect.py` against a newer store and the
capture is overwritten. The diff will be mostly noise, because ids and
timestamps change every run, and that is not what to read. What to read
is whether the suite still passes: the assertions are written against the
structural claims rather than the bytes, so a store that changed one
of them turns a test red with a message naming it.
