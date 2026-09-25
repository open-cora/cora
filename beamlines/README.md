# Beamlines

What a running keeper installation has to be told about the beamline it
serves, written down where it can be read and reviewed.

One directory per beamline, holding data only, plus the scripts here that
consume it. `2-bm` is the first.

## The one rule

**A descriptor may only carry a field that some keeper command or client
configuration accepts today.** No device family, no distance along the
beam, no vendor, no drawing, no controller back-reference. Those are real
facts about a beamline and none of them has a home in this tree: the
Equipment context holds an address, a label and a derived status, and says
at length why it holds nothing else.

This is `conventions.md`'s rule against describing machinery that does not
exist, applied one level up. A descriptor field with no consumer is a claim
about the beamline that nothing here can act on, and nothing here can
contradict either.

The one exception is `confirmed`, and it is earned rather than granted: the
difference between a value staff verified and a value read off a web page
is a fact about the record rather than about the hardware, so it is the one
thing here that describes the descriptor itself.

## Where the values come from

Every value is authored from the beamline's own sources: a `caget` sweep
against the real IOCs, or the beamline staff. Nothing is transcribed from
the sibling project, whose tree this repository does not read and whose
measurements belong to the system that made them.

An unconfirmed row is not a defect. It is the state most rows start in, and
`confirmed = false` is how a reader tells one from a checked one.

## The rule on a device reference

A device's external reference is **one record, normalized**: trimmed, cut at
the first `.`, with any trailing `:` removed. `2bmb:m1.RBV` and
`2bmb:m1.VAL` are both `2bmb:m1`, and a reference never ends in `:`.

Two spikes reached this independently, `spikes/ophyd_adapter/` from the
identity side and `spikes/conductor/` from the exclusion side, and the
short version of both is that the record name is the only string two
clients who have never met must agree on. An ophyd object's name is
whatever a startup profile passed to it, and the facility's own `DESC`
field is served empty and writable by anyone.

**References are stored already normalized in the file, and the loader
refuses one that is not.** It does not quietly normalize on the way past.
A reader of the file has to be able to see what will be registered, and
`docs/bounded-contexts/equipment.md` is clear that nothing enforces
uniqueness across devices: two spellings of one motor make two records and
nothing notices, so this file is the only place it can be caught.

The scheme is `epics-record`. `spikes/ophyd_adapter/` wrote `epics-prefix`,
which predates the record and namespace split in `conductor.claims`; under
the rule above the value is never a namespace, and the scheme string goes
onto every `DeviceRegistered` event permanently.

A claim in a conducted procedure may be coarser than a device and never
finer, so the join, when there is one, runs one way:
`scope.covers(Scope.record(ref))`. Were a device a namespace instead, a
record-scoped claim would have to search upward for its owner, and the IOC
serves a flat namespace with nothing in it saying where to stop.

## What is not here

**No catalog.** The sibling project carries a cross-facility vocabulary of
roles, families, assemblies and models because it serves several sites and
needs them to agree. The keeper serves one beamline today and has no aggregate that
could hold any of those kinds. A portable vocabulary with one beamline
behind it is a vocabulary nobody has to agree with.

**No generated documentation.** `docs/beamlines/` is written by hand. The
sibling renders its pages from its descriptors through a few thousand lines
of scripts kept in step by round-trip tests, which is the right trade at
its size and not at this one.

**No composition.** A composition in this tree is a
`conductor.procedure.Procedure` over claims, not an assembly over slots, and
it stays out until a procedure has been walked at a real beamline. See
`PLAN.md`.

## Running the scripts

```bash
uv run --with httpx beamlines/seed_devices.py \
    --descriptor beamlines/2-bm/devices.toml \
    --base-url https://keeper.example \
    --principal-id 00000000-0000-0000-0000-000000000000 \
    --dry-run
```

Tests run on the tree's own environment, with the rest of what belongs to no
single project:

```bash
make test          # from the tree root, every project and this tier
uv run pytest beamlines/tests -v
```

They borrowed the keeper's environment until the tree had one of its own, the
way that project's `infra/atlas` still does for its migration scan scripts.
That left this directory in no lane at all: nothing linted it, nothing
typechecked it, and its tests ran only when somebody typed the command.
