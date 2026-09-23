# blueapi adapter spike

**This is not production code and nothing in `apps/api`, `apps/reporter`
or `apps/conductor` depends on it.** Read [FINDINGS.md](FINDINGS.md)
first; the findings are the deliverable and the scripts are only how they
were obtained.

What a conducted run looks like when the engine sits behind Diamond's
service rather than NSLS-II's: which names exist and when, what a second
client is told, and whether the reporter's translator survives a different
transport.

The name is the family marker the other adapter spikes carry.

## Why it exists

`spikes/queueserver_adapter/` measured one service in front of a
RunEngine and recommended against an adapter behind the current
`Acquisition`. Its reasons were about queueserver specifically: a
submit-time handle no document reader can see, a lock at the wrong
granularity, and no synchronous submit.

blueapi is the other service, and it made the opposite decision about the
central question. Its architecture decision record 0003, "No Queues",
says the worker runs one task at a time, errors if asked while another is
running, and that "Queueing should be the responsibility of a different
service". If that holds, the conductor is that service and `Ledger` keeps
its job instead of acquiring a rival.

Comparing the two from documentation got as far as a prediction and no
further, which is what this repository has spikes for.

Five questions:

1. What does a second client actually get when the worker is busy, and
   does the refusal name a holder the way `Refused` does?
2. Can a caller carry its own reference into the run's record, and does
   any blueapi identifier reach a document reader?
3. Can `apps/reporter` consume this bus with a new source and an
   unchanged `translate.py`?
4. Can it run without Kubernetes, OIDC, Tiled, numtracker and OPA, or are
   those the package's requirements rather than Diamond's deployment?
5. Do the plan-level events and the run's own stop document agree, and
   what happens when a plan fails?

`FINDINGS.md` is the point. All five are answered there, and question 5
answered differently from the way the question was asked.

## What is real and what is not

The service is the package's own `blueapi serve`, the broker is a real
RabbitMQ with its STOMP plugin enabled, and the probe is an ordinary httpx
and stomp.py client of the kind any other agent at a beamline would be.
Nothing is patched, subclassed or told that a test is happening. The plans
are registered the way the package intends, by introspecting type hints on
three functions in a module on `PYTHONPATH`.

Not real: the detector. `ophyd.sim.det` computes a value rather than
reading a camera, and no device source is configured at all, so the plans
name no device parameter. That leaves out everything about how blueapi
resolves device names, which is a separate question this does not ask.

There is no beamline here and no Channel Access, unlike
`spikes/conductor/`. Leaving EPICS out also leaves out a port: two
sessions sharing this checkout have collided on Channel Access once
already.

## Running it

Two terminals, plus a broker. RabbitMQ's STOMP plugin is not on in the
stock image, so it is enabled at startup:

```sh
docker run -d --name aroc-blueapi-rabbit -p 61618:61613 -p 15673:15672 \
    rabbitmq:4-management \
    sh -c "rabbitmq-plugins enable --offline rabbitmq_stomp && rabbitmq-server"
```

Then, from this directory:

```sh
PYTHONPATH=. uv run --no-project --python 3.13 \
    --with blueapi --with ophyd --with stomp-py --with httpx \
    blueapi -c config.yaml serve
```

Then, with the service up:

```sh
uv run --no-project --python 3.13 --with httpx --with stomp-py python probe.py
```

The ports are shifted off their defaults on purpose. blueapi serves on
8765 rather than 8000, and the broker's STOMP port is published on 61618
rather than 61613, so a second session sharing this checkout does not
evict this one.

`config.yaml` is the smallest configuration the service accepts, and what
is missing from it is the substance of question 4. `findings.json` is what
the probe wrote and `FINDINGS.md` reads it. Ids and timings change every
run, so do not commit a rerun on a whim.

## The files

```
   config.yaml     the smallest configuration blueapi will serve
   spike_plans.py  three plans and one simulated detector
   probe.py        five scenarios, one bus subscriber, headers kept
   findings.json   what the service answered and what the bus carried
   FINDINGS.md     the point
```

## When to delete it

When the question of what sits in front of the engine at a multi-client
bluesky beamline is settled, which is the only reason it exists. Keep
`findings.json` if a reporter is ever pointed at this bus: the envelope
shapes in it are what arrives, and they make a fixture that needs neither
a broker nor a service.
