# Plan: a lite deployment descriptor for 2-BM

Scaffolding. Fold what survives into `beamlines/README.md` and delete
this file when the last step lands.

The two commit subjects marked done below say `deployments`, which is the
directory's name at the time they landed. `EXPANSION.md` decision 1 is why
it is `beamlines/` now, and the git history keeps the old spelling because
that is what happened.

## What this plans

One directory, `beamlines/2-bm/`, holding the facts about 2-BM that some
the keeper command or client configuration already accepts, plus the two small
scripts that consume them. Two consumers in scope: the Equipment device
register, and the reporter.

## What it deliberately does not do

**No catalog.** CORA's `catalog.yaml` carries Roles, Families, Assemblies,
Models, Methods and Capabilities because CORA serves several facilities and
needs a portable vocabulary between them. The keeper has one deployment and no
aggregate that could hold any of those kinds. A portable vocabulary with one
deployment behind it is a vocabulary nobody has to agree with.

**No docs generation.** CORA renders its deployment pages from its
descriptors through about 2,800 lines of scripts and keeps the two in step
with round-trip and drift-guard tests. The page here is written by hand
until hand-maintaining it actually hurts.

**No composition, yet.** See "The trigger for procedures.toml" below.

**Nothing transcribed from the sibling project.** CLAUDE.md forbids reaching
into that tree, and `docs/reference/conventions.md` says a measurement
belongs to the system that measured it. Every value in `devices.toml` is
authored from 2-BM's own sources: a `caget` sweep against the real IOCs,
or staff. The `confirmed` flag below is how the two are told apart.

## The rule that keeps it lite

**A descriptor may only carry a field that some keeper command or client
configuration accepts today.** No family, no `z_mm`, no vendor, no drawing,
no controller back-reference. That is
`conventions.md#do-not-describe-machinery-that-does-not-exist` applied one
level up: a descriptor field with no consumer is a claim about 2-BM that
nothing here can act on or contradict.

The one exception, and it is earned rather than granted: a `confirmed` flag,
because the difference between what staff verified and what was read off a
web page is a fact about the record itself rather than about the hardware.

## Two decisions already settled

**A device's external reference is one record, normalized.** Both
`spikes/ophyd_adapter/FINDINGS.md` (section 1, and the recommendation in
section 5) and `spikes/conductor/FINDINGS.md` (section 8) reached this
independently. The value is what `conductor.claims.Scope.record` produces:
trimmed, truncated at the first `.`, with any trailing `:` removed. So
`2bmb:m1.RBV` and `2bmb:m1.VAL` both normalize to `2bmb:m1`, and a device
reference never ends in `:`.

Claims may be coarser than a device and never finer. The join, when there is
one, is `scope.covers(Scope.record(ref))`, and it only works in that
direction: were devices namespaces, a record-scoped claim would have to
search upward for its owner, and the IOC serves a flat namespace with
nothing saying where to stop.

Normalization is load-bearing rather than tidy. `docs/bounded-contexts/equipment.md`
concedes that nothing enforces uniqueness across devices and that a caller
resolving one is about to write to whatever comes back. Two spellings of one
motor is two records and nothing notices, so the descriptor is the only place
this can be caught.

Scheme string: `epics-record`. The spike wrote `epics-prefix`, which predates
the record and namespace split in `conductor.claims`; under the rule above the
value is never a namespace, and the scheme goes onto every `DeviceRegistered`
event permanently.

**The reporter token is not a 2-BM fact.** `base_url`, the two scheme
strings and the plan map are facts about the deployment. The token is a fact
about one reporter instance: a deployment could run two reporters with two
tokens, and rotating one changes nothing about 2-BM.

`reporter.config` has already decided how to handle it. `load`'s docstring
says a deployment wanting to inject the token another way substitutes its own
loader, and `from_mapping` exists so that deployment has a function to call
rather than a format to imitate. So `config.py` is not touched, and
`__main__.py` does not grow a `--token-env` flag: that would be the second
source of truth the docstring turns down, shipped to every deployment to
serve one.

## The files

```
beamlines/README.md              what a descriptor is here, and is not
beamlines/descriptor.py          loading a register, and the reference rule
beamlines/seed_devices.py        reads a register, posts to /devices
beamlines/tests/                 the rule, and the register that keeps it
beamlines/2-bm/devices.toml      the 2-BM register
docs/beamlines/2-bm.md           the prose
```

The scripts sit at the top and take a descriptor path; the per-deployment
directories hold data and nothing else. A second deployment then costs one
directory rather than a copied script, and `2-bm` is not a Python
identifier anyway, so a script living inside it could not be imported by a
test.

`devices.toml`:

```toml
scheme = "epics-record"

[[device]]
ref = "2bmb:m1"
name = "Sample rotation"
confirmed = true
```

Three keys and nothing else. `ref` is already normalized in the file rather
than at load, so a reader sees what will be registered.

## Steps

Each is one commit that stands on its own.

**1. `docs(deployments): say what a descriptor is before writing one`** (done)

`beamlines/README.md` and `docs/beamlines/2-bm.md`, the mkdocs nav entry,
and the row in `docs/index.md`. The "Nothing describes deployment, because
there is nowhere to deploy to yet" line in that page's "What is missing"
section goes. The fenced count block in the same file is compared against the
code by `test_docs_match_code_constants.py` and is not touched.

**2. `feat(deployments): the 2-BM device register, and one rule on a reference`** (done)

`devices.toml`, `seed_devices.py`, and `beamlines/tests/`.

The seeder resolves each reference through
`GET /devices?external_ref_scheme=...&external_ref_value=...` and registers
only what comes back empty. It is not idempotent and says so in its module
docstring, in two parts rather than one. The resolve is a check and not a
lock, because Equipment enforces no uniqueness behind it. And the
`Idempotency-Key` it derives per device narrows the window without closing
it: the key expires after `IDEMPOTENCY_TTL_HOURS` and the claim is scoped to
the calling principal, so the same file seeded tomorrow, or today by someone
else, is not protected by it. What closes the gap is a person reading
`--dry-run` output.

An address that already carries two records is reported and the run exits
non-zero. Picking one would be answering the question the listing exists to
expose.

Normalization is reimplemented here rather than imported. The three apps share
no package on purpose, and `apps/conductor` is not a dependency of a seeding
script. The duplication is the cost and the test table below is what keeps the
two honest.

**3. The reporter's 2-BM settings: stopped, and not for the reason planned**

This step was written to ship `reporter.toml` minus `keeper.token`, plus a
renderer that injects the token from the environment. The token decision
still stands and is recorded above. What stopped the step is the engine.

`apps/reporter` reads the documents a Bluesky RunEngine publishes.
`spikes/tomoscan_adapter/FINDINGS.md` says 2-BM-S runs TomoScan, and
`apps/reporter/README.md` already notes that TomoScan's stream has no
documents in it at all. Two further findings from the same spike: TomoScan
mints no run identity, so the only per-scan handle is the output file path
and it is not known until the scan ends; and it has no named routine, so
the plan map has nothing to key on rather than merely being unpopulated.

So a `reporter.toml` for 2-BM would configure a client that cannot connect
to 2-BM's engine, with a plan map that cannot be filled. Writing one to
hold the shape would be describing machinery that does not exist, one level
up, which is the rule this whole directory is built on.

Three ways forward, and the choice is not this plan's to make:

- **A Bluesky engine at 2-BM.** If one runs at a station other than 2-BM-S,
  the original step 3 applies unchanged and needs only that station's
  values.
- **A TomoScan reporter.** A second reporting client, keyed on
  `("tomoscan-file", <path>)` and reporting at end of scan only. That is an
  application, not a descriptor, and `spikes/tomoscan_adapter/` is the
  measurement it would start from.
- **Neither yet.** Devices are registered, faults are reported against
  them, and no run reaches the keeper from 2-BM until one of the above exists.

The renderer is not built either, for the same reason: a script with no
descriptor to render is dead code, and `test_unloaded_modules_are_pinned.py`
exists because this tree already dislikes carrying some.

## Checks

`beamlines/tests/`, run on the tree's own environment:

```bash
uv run pytest beamlines/tests -v
```

Three things worth a test and nothing more:

- normalization, over a table that includes a field suffix, a trailing colon,
  both at once, surrounding whitespace, and a value that is already normal
- every `ref` in `devices.toml` is already in normal form, so the file cannot
  drift from the rule it exists to enforce
- the renderer refuses an unset token and refuses a destination in the repo

A CI lane for this is optional at two tests and a table. If one is added it
has to be listed in `ci-gate`'s upstream set, which currently fails closed on
every lane succeeding.

Note while here: `apps/conductor` has no CI lane at all. Out of scope, worth
its own commit, and it matters before step 2 below.

## The trigger for procedures.toml

Composition in this tree is a `conductor.procedure.Procedure` over `Claim`s,
not an Assembly over slots, and it stays out of this plan for one reason: the
conductor has never started a scan. Its acquisition seam is checked against a
double, and `apps/conductor/README.md` says so. A descriptor of 2-BM
procedures written before anything has driven one at 2-BM would be authored
from the same guessing the spikes exist to avoid.

Write it when a procedure has been walked at 2-BM against real hardware. At
that point the descriptor has something to record rather than something to
propose, and the record-scope join above is what connects its claims back to
the registered devices.
