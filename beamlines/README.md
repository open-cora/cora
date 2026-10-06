# Beamlines

What a running keeper installation and the clients around it have to be told
about a beamline they serve, written down where it can be read and reviewed.

One directory per beamline, plus the scripts here that consume it. There are
four, and all four have been swept against their own IOCs, so every row in
every register is confirmed. That now covers two instruments at 32-ID rather
than one. They are very different sizes, and the two rows 19-BM's register
does not have are the most informative thing in any of them.

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
facts about a beamline and none of them has a home in this tree.

A register row carries four keys, and what changed is which. Equipment
held an address, a label and a derived status; it now also holds the
beamline a device is at and, optionally, the functional cluster it
belongs to. So `beamline` and `group` are legal here, and they became
legal on the day the keeper command started accepting them rather than
on the day somebody wanted to write them down. That order is the rule
working, not a loophole in it.

**`group` is not the start of a catalog**, and the distinction is worth
holding on to. It is a value rows share rather than a thing that owns
them: a group exists while some device says that word and stops
existing when the last one stops. There is no group anywhere else, no
nesting, no ordering, and nothing that can be said about a group rather
than about a device. A portable vocabulary of families and assemblies
is still refused below, for the reason given there.

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

**A register records how a row was confirmed and never when.** The flag and
the comment above it say which of the three sources a row came from, because
that is what decides how far to trust it and nothing else can tell you. When
it happened is `git blame` on the file, which gives a date per row, cannot
drift, and updates itself the day somebody re-sweeps. A date written into the
file would be a second copy of a fact git already holds exactly, maintained by
hand, and wrong the first time a row changed without it. It would also be a
field no command reads, which the one rule above refuses on its own.

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

It also does not only find things that exist, which is the harder lesson and
is why every answer is read back before it becomes a row. See the paragraph
on 19-BM below.

**This was a technique and not a script, deliberately.** Generalising it from
a single observation would have been the guessing this whole directory exists
to avoid, so a second run was set as the thing that would make it worth
automating, and any such tool would produce a descriptor for a person to read
rather than registering anything itself.

It has now been run at all four beamlines, so that trigger has fired and the
script is worth writing rather than worth waiting for. Two of those runs
found limits worth building into it, and the second is the serious one.

At 32-ID the software named three of the five motors the micro-tomography
station has there, so a tool trusting it alone would have produced a
register missing two real axes. That is an omission, and a reader can see
it.

**At 19-BM the software named two records that do not exist.** Asked for its
sample axes it returned `TODO_SAMPLE_X` and `TODO_SAMPLE_Y`, because the
beamline is in commissioning and nobody has filled them in. Neither string
contains a `.` or a trailing `:`, so both satisfy the reference rule below
and the loader accepts them. A register holding them would be well formed,
would say `confirmed = true` with as much justification as any other row, and
would name nothing at all.

**So the technique has a third step, and it is not optional: read each
reference back.** Asking what the software drives gives a candidate, not a
device. One `caget` per answer separates a record from a string that merely
looks like one, and it is what kept two fictions out of 19-BM's register. The rule below checks the shape of a reference and has no way to check
that anything answers to it.

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

## The adapter register

Each beamline carries an `adapters.toml` beside its `devices.toml`, saying
which adapter fills which seam there. `devices.toml` says what hardware
exists; this says what software reaches it.

```toml
[driving]
scan_engine = "tomoscan_engine"      # conductor Running
control_system = "epics_control"     # conductor Adjusting

[recording]
deliveries = "tomoscan_records"      # where the reporter is delivered to from
store = "none"                       # reporter Locating
data_format = "dxchange_hdf5"        # reporter Describing

[processing]
recon_engine = "none"                # no seam for this exists yet
data_transfer = "none"               # nor this
```

**A value is an adapter module name, `none`, or `unsurveyed`**, and the
three mean different things. A name says the beamline runs that adapter.
`none` is measured absence. `unsurveyed` means nobody has asked the
beamline, which this page already treats as an honest entry rather than a
gap, and collapsing it into `none` would turn an open question into a
finding.

**Every name is checked.** `tests/test_adapters.py` resolves each one
against the adapters of the app that owns the slot, so renaming a module
reddens a test rather than leaving a register that quietly lies. It also
refuses any value but `none` or `unsurveyed` in a slot no seam exists for,
which is what makes it safe to list reconstruction and data transfer here
before either is built.

`deliveries` is the reporter's own word for that slot, not a new one. Its
entrypoint already picks between the three sources in a function of that
name returning `Delivering`, and says why it is not named after any engine:
a TomoScan server publishes no documents, and one of the three is a capture
file on disk with no engine behind it at all. The direction is in the word,
which a feed or a channel would have left open.

**The keys name roles, not products**, which is the rule
`apps/reporter/docs/glossary.md` already states for **store** and
**engine**: which one a deployment runs is the deployment's fact. So the
slot is `control_system` rather than `motion`, because what it sets is any
record and not only a motor, and `data_format` rather than `describer`,
because what differs between beamlines is the format they write and not
what the code does with it.

**It does not say what is running.** A beamline whose reporter is installed
and disabled still names the feed it is configured with. Which services are
up is a different kind of fact and lives in `docs/beamlines/index.md`.

`facility.toml` at the root of this directory holds the slots that are one
value for the whole facility rather than one per beamline. Today that is
the inference profile, `argo`, resolved against the thinker's
`infra/thinking/` because a profile is a deployment artifact and not
something the package ships.

The thinker has no per-beamline row and should not get one. One thinker serves the
facility: an inquiry names an execution, and where that ran is the
execution's fact, which is the argument `apps/thinker/src/thinker/config.py`
makes under "Why there is no beamline".

## What is not here

**No catalog.** The sibling project carries a cross-facility vocabulary of
roles, families, assemblies and models because it serves several sites and
needs them to agree. The keeper serves four beamlines today and has no
aggregate that could hold any of those kinds. A portable vocabulary earns
its keep where sites that must agree would otherwise diverge, and four
registers at one facility have not diverged yet, nor has anything forced
them to.

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
