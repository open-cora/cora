# Queueserver spike

What a conducted run looks like when the engine is not in this process:
which names exist and when, whether a per-device claim means anything
against a shared queue, and whether a walk can still be synchronous.

## Why it exists

`spikes/conductor/` answered the identity question for a bare RunEngine
and said so in its own limits: "It did not run queueserver, so section 7
answers the identity question for a bare RunEngine only." The sentence
after it guessed that queueserver "assigns an item uid at submit time,
which is a different and probably better answer".

Half of that guess is right and the half that matters is wrong, which is
why this exists rather than the guess being written into a design.

The framing carried forward was that queueserver serves the identity
question and nothing else. It does not. A bare RunEngine runs in the
conductor's own process, so the conductor is the only writer by
construction. RE Manager runs in its own process, behind a queue held in
Redis that any client can add to. That moves the device-claim question,
which `spikes/conductor/` had closed, back open.

Five questions:

1. Does a per-device claim survive a shared queue? The conductor's
   `Ledger` is in-process and single threaded. Another client's queue
   item is neither.
2. What does queueserver offer instead, and at what granularity?
3. Which names does a conducted run have, at which moment, and which of
   them can a reporter watching the document stream actually see?
4. Can a walk stay synchronous, holding each claim for exactly as long
   as its step runs?
5. Do the two sides agree on how a run ended?

`FINDINGS.md` is the point. All five are answered there.

## What is real and what is not

There is no beamline here and no Channel Access, unlike
`spikes/conductor/`. RE Manager is the package's own `start-re-manager`,
the queue lives in a real Redis, and both clients in the collision
scenarios are ordinary `ZMQCommSendThreads` clients of the kind any other
agent at the beamline would use. Nothing is patched, subclassed or told
that a test is happening.

The devices are `ophyd.sim`. A simulated motor is enough to put two queue
items on one device, which is all question 1 needs, and leaving EPICS out
leaves out a port: two sessions sharing this checkout collided on Channel
Access 5064 once already.

`startup.py` builds the RunEngine rather than letting RE Manager build
one, so a subscriber can write start and stop documents to
`documents.jsonl`. That file is this spike's stand-in for the 0MQ stream
`apps/reporter` consumes, minus a second port.

## Running it

Redis and the manager both sit on non-default ports, for the reason
above. Two terminals:

```
docker run -d --name aroc-qs-redis -p 6399:6379 redis:7-alpine

uv run --no-project --python 3.13 \
    --with bluesky-queueserver --with bluesky --with ophyd \
    qserver-list-plans-devices --startup-script startup.py --file-dir .

uv run --no-project --python 3.13 \
    --with bluesky-queueserver --with bluesky --with ophyd \
    start-re-manager --startup-script startup.py \
    --existing-plans-devices existing_plans_and_devices.yaml \
    --user-group-permissions user_group_permissions.yaml \
    --redis-addr localhost:6399 --redis-name-prefix aroc_spike \
    --zmq-control-addr 'tcp://*:60715' --zmq-info-addr 'tcp://*:60725'
```

Then, with the manager up:

```
uv run --no-project --python 3.13 \
    --with bluesky-queueserver --with bluesky --with ophyd python probe.py
```

`existing_plans_and_devices.yaml` is generated rather than committed,
which is why the first command builds it. It is derived from
`startup.py` and has to be rebuilt whenever that changes. RE Manager
refuses to start without it, and the error it prints names a command line
option that does not exist: it says `--existing-plans-and-devices`, the
flag is `--existing-plans-devices`.

`findings.json` is what the probe wrote, and `FINDINGS.md` reads it. Ids
and timings change every run, so do not commit a rerun on a whim.
