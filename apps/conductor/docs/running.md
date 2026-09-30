# Running one

This page is for whoever installs a conductor at a beamline and keeps it
running.

## What it needs

Network access to the record, and whatever talks to the hardware. Nothing else:
no database, no broker, no inbound port. It dials out and nothing ever dials in.

It runs at the beamline rather than in a data centre. The protocols that talk to
motors work on the local network only, so the process has to be where the
hardware is.

An engine is optional. Without one, every set still runs and each
run step is refused as it is reached, which is a real deployment rather
than a broken one: a beamline that only moves things needs no engine at all.

## Starting one

```sh
python -m conductor --config conductor.toml
```

It asks the record what work is waiting for its beamline, takes one job, walks
it, and asks again, for as long as it is left running. It is not a server and
listens on nothing.

## Configuring one

```toml
beamline = "2-bm"

[keeper]
base_url = "https://keeper.example"
token = "a-conductor-token"

[run]
profile = "beamline_2bm.startup:run"
```

Three settings, and the third is optional.

**The beamline** is set here rather than worked out from the token. Asking what
is waiting at a beamline is a question anybody may ask, and a token is who you
are. Tying them together would mean an operator could not ask what 7-BM is
waiting on without holding 7-BM's identity, and one wrong grant would become a
conductor driving hardware at the far end of the building.

**The run profile** names something importable that hands back a ready
engine. It is a dotted path rather than a block of settings because an engine
and a set of runnable routines are objects a text file cannot hold. Leave the
whole section out at a beamline with no engine.

The conductor never builds an engine of its own. Where one exists, the
deployment hands it over. That is what lets the same program run at a beamline
with no engine, a beamline with a bare one, and a beamline with a managed queue,
changing only what sits behind one seam.

**Nothing configures whether datasets are registered.** A conductor records
where a run's data is exactly when its engine answers with a location, which
the engine adapter declares, and it does that against the same keeper and the
same token it took the work from. An engine answering with a name instead has
nothing a conductor could file, so something watching the store files it.

That is a decision the configuration cannot express rather than a default it
omits. A switch here could be turned on at a beamline whose engine answers
with names, and every run would then register an address resolving to
nothing. Leaving it unsayable is cheaper than refusing it at startup.

## Stopping one

A stop lands between jobs rather than inside one, so a polite shutdown can take
as long as the scan in progress. That is the right trade: the alternative is
abandoning a step halfway.

Killing it harder leaves the hardware wherever the last step put it. That is
measured rather than feared. A driver was killed mid-move and the motor
travelled to its target with nothing alive that had asked for it, and no stop
message was ever sent. A hard kill offers nothing to hang cleanup on.

So if something must stop when its driver is abandoned, that needs a watchdog
next to the hardware. It is not this, and it is not the record either. What a
killed walk does leave behind is its record: every step that finished before the
process died is already filed, because outcomes go out as they happen.

## What it leaves behind when things go wrong

```
   a step is refused        something else holds the hardware it names.
                            the record says which job holds it.

   a step breaks            the seam raised. one line of text goes on the
                            record, and the walk stops there.

   later steps              reported as skipped, so the record shows the
                            whole job and where it stopped.

   the process dies         the steps that finished are on the record. the
                            job stays open, because nothing closed it.
```

## Running the tests

```sh
uv sync --all-extras
uv run pytest -q
uv run ruff check src tests typings && uv run ruff format --check src tests typings
uv run pyright src tests
```

The suite starts a simulated control system and talks to it over a real socket,
so it takes about ninety seconds and needs no beamline. Tests that need it carry
the `channel_access` marker, and each is handed both motors unlatched, at zero
and at rest first. `make test-core` skips the ones that drive motion.

Homing between tests goes through the adapter rather than through a bare write,
and that is not tidiness. A bare write returns while the motor is still
travelling, so every test used to inherit a motor still drifting back from the
one before it. One test passed for months on that residual motion and failed
eight times out of eight when run alone.
