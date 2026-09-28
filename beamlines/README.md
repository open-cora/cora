# Beamlines

What a running keeper installation and the clients around it have to be told
about a beamline they serve, written down where it can be read and reviewed.

One directory per beamline, plus the scripts here that consume it. `2-bm` is
the first and today the only one.

Two kinds of thing live in a directory. A **register** is data this system will
hold a record of, and `devices.toml` is the one that exists. A **client
configuration** is what a process at that beamline has to be handed in order to
start. Both are descriptors and both answer to the one rule below.

Credentials are neither, and they are not here. A token lives in its beamline's
own home directory at mode 600, where the operating system is what keeps one
beamline out of another's. Nothing in this repository should ever be able to
authenticate as a beamline.

## The one rule

**A descriptor may only carry a field that some keeper command or client
configuration accepts today.** No device family, no distance along the
beam, no vendor, no drawing, no controller back-reference. Those are real
facts about a beamline and none of them has a home in this tree: the
Equipment context holds an address, a label and a derived status, and says
at length why it holds nothing else.

Equipment was once the only consumer that rule could point at, and it reads
that way. It is no longer. `POST /procedures` takes a named routine over a
beamline's records, a conductor is configured with the beamline it drives and
where to reach the keeper, and a thinker is configured with what does its
thinking. Each of those is a real consumer today, so the rule has got more
permissive without being relaxed: what it still refuses is a field with no
reader anywhere.

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

### Ask the acquisition software what it drives

Of the two sources above, there is a third that is better than either and
that produced every confirmed row in this directory: **ask the software
already driving the beamline which records it drives.**

Where an acquisition package is configured over Channel Access, its own
settings are records whose values are the names of other records. Reading
them is an ordinary `caget` and it needs no agreement with anyone:

```bash
caget -w 2 <prefix>:RotationPVName <prefix>:SampleXPVName <prefix>:CameraPVPrefix
```

Two things make this better than reading a motor list. It is **record to
record**, so nothing is being translated between one system's model and
another's, which is the failure the reference rule below exists to prevent.
And it returns a **role** rather than a position in a crate: a motor list
says a thing is the hundred and second channel, while this says it is what
turns the sample. The names in this directory are authored from those roles,
which is why they can be more useful than the facility's own description
field, and why a row sourced this way is `confirmed = true`.

It does not find everything, and the gaps are informative rather than
annoying. A detector arrives as a prefix, which the rule below cannot
accept. A safety interlock arrives as a record the beamline reads and does
not own. Both are decisions to make rather than rows to write.

**This is a technique and not a script, deliberately.** It has been run at
one beamline. Writing a tool that generalised it would be generalising from
a single observation, which is the guessing this whole directory exists to
avoid; the second beamline is what would make it worth automating, and it
would produce a descriptor for a person to read rather than registering
anything itself.

## The rule on a beamline name

A directory's name is the beamline's identity in this system, and it is
load-bearing in a way nothing enforces. Three places hold the same string and
none of them compares itself to another.

```
   beamlines/2-bm/          this directory, where a person writes it down
   Procedure.beamline       the keeper's routing key, stored as written
   conductor.beamline       which beamline a conductor asks for work at
```

The keeper stores it and compares it as written. Its Execution page is explicit
that this is deliberate: there is no Beamline aggregate and there will not be
one, because a second register of which beamlines exist would be a thing to
keep in step with these descriptors for no reader's benefit. The conductor is
equally explicit from the other side, that `2-bm` is the form this directory
uses and that nothing in that package enforces it.

So this directory is the register of beamline names by default rather than by
declaration, which is worth knowing before renaming one.

**A mismatch is silent.** Nothing refuses a name nothing recognises. A dispatch
to a beamline no conductor asks for sits waiting, and a conductor asking for a
beamline nothing dispatches to looks exactly like a quiet day. Neither reports
an error, because neither side has anything to check against.

The form is lower case with hyphens, as the sector and station are written.

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
`apps/keeper/docs/bounded-contexts/equipment.md` is clear that nothing enforces
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

**No composition.** Not an assembly over slots, and not yet anything else
either. What a written-down routine would become has moved since this was
written: the keeper now holds a Procedure of its own, with the beamline on it
and a route that defines one, so such a descriptor would be seeded through
that rather than held client-side as a `conductor.procedure.Procedure` over
claims. The destination changed; the reason for waiting did not.

The trigger is worth stating, because it is a decision rather than a delay. A
conductor has never started a scan: its engine seam is checked against a
double, and that project's own README says so. A descriptor of a beamline's
procedures written before anything had driven one there would be authored from
the same guessing the whole descriptor exists to avoid. Write it once a
procedure has been walked against real hardware, when the file has something to
record rather than something to propose. The record-scope join above is what
will connect its claims back to the registered devices.

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
