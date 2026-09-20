# Store adapter spike

**This is not production code and nothing in `apps/api` depends on it.**
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

## Why it lives outside `apps/api`

Nothing here is covered by ruff, pyright, tach, pytest or any CI lane. All
of those are invoked with explicit paths from `apps/api`, so a directory at
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
uv run --project apps/api python spikes/tiled_adapter/resolve.py
```

Step 1 cannot use `--project apps/api`. The store's client drives its own
server through `starlette.testclient`, and `apps/api` pins `httpx2`
alongside `httpx` for its own test client; that code path picks up the
wrong one and refuses with a `TypeError` about the URL type. Step 2 needs
`apps/api` and must not have the store's client beside it. `nodes.json` is
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
| `nodes.json` | Captured output. Committed, because it is the evidence. |
| `resolve.py` | The join into AROC, and every candidate key run through the real `Identifier`. |

`resolve.py` posts no dataset, because Custody does not exist yet. It
assembles the value that slice would be handed and puts it through the
value object the record would inherit, which is the part that can be wrong
today and expensive to change later.

## Deleting it

When the dataset leg of the reporter lands. Keep `nodes.json` and move it
to `apps/reporter/tests/`, the way `documents.json` moved when the
translation core started asserting against it.

The sibling spike is due for the same treatment now that the reporter is
nearly whole, and two spike directories where one is stale reads worse than
either alone.
