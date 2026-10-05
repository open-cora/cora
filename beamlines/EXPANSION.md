# Expansion: four beamlines, and what that changes

Planning. It revises a single-beamline plan that has been folded into
`README.md` and deleted; where this disagrees with anything left there, this is
later.

## What is being expanded to

| Beamline | Instruments named | State |
| --- | --- | --- |
| 2-BM | micro-tomography | operating, engine measured |
| 7-BM | radiography with spectroscopy-alike enhancements; the internal docs also list high-speed imaging and micro-tomography | operating |
| 19-BM | micro-CT | commissioning |
| 32-ID | high-speed imaging, transmission X-ray microscope; the internal docs also list a projection microscope and micro-CT | operating |

The instrument count is not settled. The facility's internal index lists
more instrument pages than the four-plus-two above, so the first thing to
pin is what counts as an instrument here and which of those pages describe
one.

2-BM's row says "measured" because it was, on `arcturus` rather than from
documentation: `tomoscan` is the installed acquisition package and none of
bluesky, ophyd, pyepics, caproto, tiled, queueserver or blueapi is present
at all. The running screens are macroed to `tomoScan_2BM` and
`tomoScanStream_2BM` over the `2bm:`, `2bmb:`, `2bma:` and `2bmHXP:`
prefixes.

## The shape, drawn

Three views of the recommendation below: the topology, one beamline in
detail, and what a descriptor feeds.

```
  beamline networks: Channel Access and 0MQ, local only
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │     2-BM     │ │     7-BM     │ │    19-BM     │ │    32-ID     │
  │  micro-tomo  │ │  radiography │ │ commissioning│ │  HSI + TXM   │
  ├──────────────┤ ├──────────────┤ ├──────────────┤ ├──────────────┤
  │  EPICS IOCs  │ │  EPICS IOCs  │ │  EPICS IOCs  │ │  EPICS IOCs  │
  │  engine      │ │  engine      │ │  engine      │ │  engine      │
  │  conductor   │ │  conductor   │ │  conductor   │ │  conductor   │
  │  reporter    │ │  reporter    │ │  reporter    │ │  reporter    │
  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
         │                │                │                │
         └────────────────┴───────┬────────┴────────────────┘
                                  │
                  bearer token, one per beamline
          measured: 10.54.113.0/24 reaches 164.54.113.0/24
                                  │
                                  ▼
                  ┌───────────────────────────────┐
                  │  central host, not tomo1      │
                  │                               │
                  │   apps/keeper  REST + MCP     │
                  │   Postgres     event log      │
                  │                one Policy     │
                  └───────────────────────────────┘
                                  ▲
                                  │  apps/thinker arrives, reads
                                  │  once, answers once, exits
```

The thinker is drawn arriving rather than as a box in either half, because it
is the only one of the four that is invoked rather than run, and the only one
no protocol holds anywhere. Where it runs is decided by what sits behind its
inference seam, which is covered in decision 4.

Everything above the line is local-network in practice rather than by
necessity: Channel Access does not find an IOC across a sector by broadcast,
and a subscription has no offset to come back to. Given an explicit address
list Channel Access does cross, which is measured and is not what an earlier
draft of this file assumed.

```
  one beamline, one claim boundary

    instrument A            shared optics            instrument B
    high-speed imaging      front end, ID, DCM       TXM
           │                        │                        │
           └────────────────────────┼────────────────────────┘
                                    │
                    Channel Access: one flat namespace
                                    │
              ┌─────────────────────┴─────────────────────┐
              │                                           │
        control seam                              the engine owns
        caput, verified                           the inner loop
              │                                           │
  ┌───────────┴───────────┐    run     ┌──────────────────┴──────────┐
  │    apps/conductor     │ ─────────► │   the engine                │
  │                       │            │                             │
  │    ONE Ledger, for    │            │   RunEngine  ──► documents  │
  │    the whole beamline │            │   TomoScan   ──► NOTHING    │
  └───────────┬───────────┘            └──────────────┬──────────────┘
              │                                       │ 0MQ
              │ HTTP: resolve a device                ▼
              │                          ┌────────────────────────┐
              │                          │     apps/reporter       │
              │                          └────────────┬────────────┘
              │                                       │ HTTP: report runs,
              │                                       │ register datasets
              ▼                                       ▼
     ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  central the keeper  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
```

The instruments converge before the conductor, which is decision 2 drawn:
split the ledger and nothing stands between two walks and the shared
monochromator. The `TomoScan` branch is the critical path, not a footnote.

```
  what a descriptor feeds

  beamlines/32-id/
    │
    ├── devices.toml ──── seed_devices.py ──────► POST /devices
    │     one record per row, normalized                (Equipment)
    │
    ├── principals.toml ────────────────────────► X-Principal-Id
    │     account name to actor id                      on every client
    │     (Access holds no name, so this
    │      map has no home inside the API)
    │
    ├── reporter.toml ─── + token from env ─────► apps/reporter
    │     base_url, store table                         (blocked: engine)
    │
    └── conductor.toml ── + token from env ─────► apps/conductor
          beamline, base_url, run profile               (needs a host)
```

Only the first line works today. `principals.toml` does not exist yet, and
`reporter.toml` is blocked behind the engine question rather than the token
question.

Two corrections to that diagram since it was drawn. The reporter no longer
carries a map from an engine's routine names onto this system's ids: the
setting was deleted rather than renamed, because the keeper composes the work
and the ids now travel in the engine's own metadata. And a conductor
configuration is the one descriptor here that nothing blocks on an engine,
since a conductor with no run profile still drives every set it is given.

## Two paths, and only one of them is gated on engines

This section is rewritten against `execution-topology`, a decision settled
in conversation the same day and not yet in the repo, which supersedes the
framing that the conductor is only a peer client. The correction matters
enough to state plainly: an earlier draft of this plan said expansion was
gated on engine coverage, and that is true of one path and not the other.

**The recording path is gated on engines.** `apps/reporter` reads the
documents an engine publishes. `spikes/tomoscan_adapter/FINDINGS.md`
measured the engine 2-BM-S runs and found no documents at all. So a
`reporter.toml` for that instrument configures a client that cannot
connect, which is why the single-beamline plan stopped where it did.

That blocker was three things when this was written and is now one. One was
that nothing could key a plan map, and there is no plan map any more. The
second was that a run had no identity until it ended, and 2-BM now mints a
`ScanUUID` at the start of every scan, so the natural-key half is answered
for that instrument before the engine half is. What is left is the shape of
the stream, and no upstream change is going to turn it into documents.

**The driving path is not.** The conductor holds two seams for driving and
`Adjusting` needs no engine: a procedure walks over Channel Access at a
beamline that has never heard of an engine. No beamline in this set runs a queue manager,
so the engineless shape is the common one here rather than the exotic one.

```
   engineless    conductor --Adjusting--> EPICS     the conductor IS the engine
   bare engine   conductor --Running-->  RunEngine  it owns the writer slot
   managed       conductor --Running-->  RE Manager it is one client of several
```

That reorders the critical path. It is not a second reporting client for a
document-less engine. It is **`conduct()` becoming a durable service**:
long-lived, remotely abortable, and safe across its own restart.
`conduct.py` currently disclaims all three, and a SIGKILL mid-move left a
motor driving itself with nothing alive commanding it. Four beamlines make
that disclaimer a roadmap gap rather than a boundary.

Second in line is how a conducted run reaches the record at all. The
driving-side verbs do not exist: `execution.md` reserved `start_run` for
them and nothing issues it. Until that lands, a walk at an engineless
beamline drives hardware and leaves no run behind.

The instrument, engine and store table is still worth building, because it
says which beamlines can use the reporting path today and which are
engineless. It is no longer what everything else waits on.

## Decision 1: the word "deployment" is already taken

`authority/aggregates/policy/state.py` says "one deployment authorizes
against one policy, selected by id in settings," and `.env.example` uses
the word the same way. In the code, a deployment is one keeper installation.

If one installation serves four beamlines, then a directory per beamline
named for deployments means beamline while the code means installation, and
the glossary's rule that each term is defined once is broken.

**Done: the directory is `beamlines/`, the docs section is
`docs/beamlines/`, and "deployment" keeps meaning the installation.** The
rename cost one commit at this size and would have cost a great deal more
once four descriptors and their scripts existed. It stays contingent on
decision 3: if each beamline later gets an installation of its own, the
older word fits again and the directory moves back.

## Decision 2: the unit is a beamline, not an instrument

32-ID's two instruments share a front end, an insertion device and a
monochromator. So do 7-BM's, and 2-BM's two hutches.

The conductor's `Ledger` is per-process, and `spikes/conductor/FINDINGS.md`
is the measurement of what two writers on one device do to a scan. Two
instruments modelled as two separate units means two conductors, two ledgers,
and nothing at all between them and the shared monochromator. The facility
layer does not save it either: the access-security spike found the IOC-side
gate can refuse a write per record in under a millisecond and **cannot tell
two processes on one workstation apart**.

That spike's findings page was recorded here as never committed and
unrecoverable, and that was wrong on every count. It was committed, on this
branch, with the measurement in the commit subject; it was removed later and
deliberately, by the change that dropped the spikes and undertook to keep
what they had established; and its full text is still in the history, where
`git log --diff-filter=D` over that directory will find it. The measurement
is 0.7 ms for the refusal, and the page states in its own opening that the
gate cannot tell two processes on one workstation apart.

So nothing here rests on prose alone and no measurement needs retaking. The
sentence above is the correction as much as the claim: a statement that
evidence is gone is itself a claim, and this one survived several passes
without anybody running the search that refutes it in one command.

**Recommendation: one device register, one conductor and one claim ledger
per beamline. An instrument is a partition inside it, not a unit of its own.**

**The ledger does not cover a human.** It is in-process, so it cannot see
a scientist at their own session on the same beamline, which stays a second
writer whatever the keeper does. `execution-topology` names that as the condition
under which a queue manager is adopted rather than built, and lists the
tripwires to watch for. One ledger per beamline is the right boundary for
the writers the keeper runs; it is not a claim to arbitrate the ones it does not.

The partition needs no new descriptor field, which matters because of the
one rule. A device's `name` is this system's own label, authored here, so
`name = "TXM sample rotation"` carries the instrument without a column that
no keeper command accepts. The partition earns a real field on the day a
procedure descriptor needs to select by it, and not before.

## Decision 3: one installation, which is what creates the auth problem

**Settled: one keeper installation serving all four beamlines.**

The alternative is not the strawman an earlier draft of this gave it. It is
what runs today: on arcturus, a uvicorn and a Postgres both bound to
`127.0.0.1`, as the beamline's own account. A per-beamline installation on
the acquisition computer has no authentication problem at all, because the
only callers are processes on that machine. Four of those would be a
working system.

What one installation buys is one record. Actor ids and operation ids mean one
thing, a question that spans beamlines has somewhere to be asked, and there
is one migration path, one backup and one restore drill rather than four.

What it costs is stated below, and the first cost is the one an earlier
draft missed entirely: **centralizing is what creates the authentication
problem.** A loopback service authenticates nobody because there is nothing
to authenticate. Put four beamlines on a shared network writing into one
record, and telling them apart becomes load-bearing. Decision 7 is that
problem, and it exists only because of this decision.

The second cost is unchanged. **Authority has no resource scoping.** A
permission is a `(principal, command)` pair and nothing else. There is no
subject, no beamline and no instrument in it. `surface_id` is not the seam:
it names the arrival surface, HTTP or MCP, is derived from the process, and
`policy_authorize.py` says outright that it is accepted and not consulted,
because no aggregate models a surface.

So a principal granted `FaultDevice` so that 19-BM can report a fault may
fault 2-BM's camera. Four installations would get that isolation physically
and for free, and one Actor per beamline (decision 5) makes the gap more
visible rather than less, because the principals now line up exactly with
the things that ought to be isolated.

Two things make it defensible anyway. The pair shape prevents the worst
version: permissions are not two lists, so granting a principal one command
grants it one command and not the cross product. And at the control layer
these beamlines have no mutual protection today either, since the access
gate `spikes/access_security/` measured must be configured per record to
exist at all.

**The trigger to revisit is a beamline team asking to be protected from
another beamline's principal.** At that point the choice is resource
scoping in Authority, a real domain change, or splitting the installation
back into the loopback shape that already works. Record it, do not build
for it.

## Decision 4: where each part runs

- **`apps/keeper` and Postgres: central, one host, reachable over HTTPS from
  every beamline.** Not `tomo1`: that is a two-GPU compute node with the
  driver unloaded, and a database sharing a host with reconstruction jobs
  is a bad trade for both.
- **`apps/conductor`: at the beamline, one per beamline.** Channel Access is
  a local-network protocol and a motor is not driven from a datacenter.
  That is the app's own stated reason for existing as a separate project.
- **`apps/reporter`: at the beamline**, because a subscription is local, or
  in the engine's own process, for which the README already has the recipe.
- **`apps/thinker`: nothing pins it, so it goes wherever its thinking does.**
  It needs the record and whatever does its thinking, and no database, no
  queue and no inbound port. It runs as a service now rather than being typed,
  so what is open is where, not whether; today that means the central host.

That fourth row is a different kind of answer from the three above it, and it
is worth not flattening. Each of the others is held somewhere by something
physical. A thinker is held by whichever of its two attachments is heavier,
and today both are light:

```
   deterministic   Inference ──► pure Python    nothing pins it
   local weights   Inference ──► a GPU host     the weights pin it
   hosted model    Inference ──► HTTPS          egress pins it
```

**The second row is where this is going next, and it needs a host this plan
has not asked for.** The only GPU named anywhere here is `tomo1`, and its
driver was measured unloaded, so it is the candidate rather than the answer.
Note that this is a second host request and it wants the opposite property
from the first: the keeper wants durability away from compute jobs, and a
thinker with local weights wants the compute. Both should go to whoever
administers those machines in one conversation.

Reachability is answered, favourably, and by measurement. arcturus sits on
the private `10.54.113.0/24`, reaches no part of the internet with no proxy
set, and reaches `tomo1` on the routable `164.54.113.0/24`. So a central
host on the routable subnet is reachable from a beamline without opening
anything through the boundary.

Distribution is answered too, and needs no new mechanism. `tomoscan` got
onto arcturus inside a conda environment under the beamline account's NFS
home, on a share every machine mounts. The keeper's clients arrive the same way
rather than by reaching a package index that is not there.

## Decision 5: one Actor per beamline, because that is the account there is

Access holds **no name** for an Actor, and says why: "the actors this system
sees are service accounts, and a service account is named where it is
provisioned." An actor is a UUID and an on/off switch.

**The granularity is the beamline, not the client.** An earlier draft argued
for one Actor per client, conductor separate from reporter, on the grounds
that they do different things and should be refused differently. Each
beamline has one service account and that is the only account there is: at
2-BM both processes run as `2bmb`, so whatever file one uses to prove
itself the other can read. Separating them in the keeper while the operating
system does not separate them is ceremony, and it would put a distinction
into the record that nothing enforces.

So four principals, one per beamline. What is lost is "which of the two
did this"; what is kept is "which beamline did this", which is the boundary
that actually exists. It becomes worth revisiting if a beamline ever runs
its two clients under different accounts.

**The rule underneath is per account, and the thinker is where that matters.**
Per beamline is not the principle, it is what the principle evaluates to at a
beamline, because each beamline has exactly one service account. The principle
is the sentence above about ceremony: do not model a distinction the operating
system does not enforce. Read that way, the last paragraph's own caveat and
open question 4 below are the same rule seen from two other sides.

A thinker is the first case where the two come apart, and it comes apart in
the direction that adds one. It is not at a beamline: it is handed an
execution and the record tells it where that work ran, which is why its
configuration refuses a beamline setting. It runs on another machine under
another account, so the operating system does separate it, and the rule that
merges a conductor with a reporter gives a thinker a principal of its own.

**Five, then, and a rule rather than a count.** Writing the number down is
what goes stale: adding four reporters later adds no principals at all, and
reorganising one beamline's accounts changes the answer without changing the
rule. Two thinker configurations on one host under one account are still one
principal, for the same reason.

**`svccora` is named for the sibling project, and is unused.** That it is
unused settles it: there is no migration to weigh against the name, so what
gets provisioned is named for this system. It would not have broken
`test_no_sibling_project_vocabulary.py`, which matches `cora` on a word
boundary `svccora` does not offer and which scans `apps/keeper` only, but a
name carried through every descriptor and every log line for a system with
no other connection to the sibling is a cost with nothing on the other
side.

**Correction: the account-to-Actor map is not a descriptor fact.** An
earlier draft said it had no home inside the API and belonged in the
beamline descriptor beside what a reporter was then told about an engine's
routine names. Under decision 7 that is wrong.
`IdpConfig.subject_bindings` holds `(issuer, subject) -> actor_id` in
the keeper's own settings, and `StaticSubjectMapper` is documented as sufficient
for "roughly ten humans plus one or two service accounts", which is this
scale several times over. The keeper resolves the principal from the token
itself, so the descriptor needs an actor id only for a client that sends
`X-Principal-Id`, which today is only `seed_devices.py` and stops being
true the moment that carries a token too.

## Decision 6: where to start

Two different firsts, because the two kinds of work have different risks.

**19-BM for the first real device register.** It is in commissioning, so a
wrong row costs nothing, the addresses are being written down right now by
people who are choosing them, and the register can be authored as the
beamline is built rather than reverse-engineered from a running one.

**2-BM for the first reporting work.** It is the one instrument in this set
whose stack has actually been measured, by `spikes/tomoscan_adapter/`. Every
engine decision made there is made against a finding rather than a guess,
which is the discipline the other five spikes set.

## Decision 7: per-beamline signed tokens, and only because of decision 3

This decision exists only because the installation is central. It would be
empty otherwise.

**Measured first.** arcturus sits on `10.54.113.119/24`, reaches no part of
the internet with no proxy configured, and reaches `tomo1` on the routable
`164.54.113.0/24`. So a central host on the routable subnet is reachable
from a beamline, and any identity provider outside the site is not: the keeper
could not fetch its keys and a client could not fetch a token. That rules
out a hosted provider by measurement rather than by preference.

Three ways to answer "which beamline is calling":

```
  1  the client says so            X-Principal-Id, the keeper believes it
  2  something in front says so    a proxy maps source address to principal
  3  the client proves it          a signed token the keeper verifies
```

**Chosen: 3, minimally.** Not a hosted provider and not Keycloak. The keeper's
verifier wants a JWKS document and a signature; it performs no OIDC
discovery and needs no token endpoint. So: one keypair, its public half as
a static JWKS served on the central host's own loopback, a signing script,
and one token per beamline in that beamline's NFS home at mode 600. Four
subjects in `subject_bindings`. `apps/reporter` needs no change, because it
already sends `Authorization: Bearer`.

**Why not 2, which is genuinely less machinery.** A proxy mapping source
address to principal is a few lines of configuration, and at beamline
granularity it is honest, since every process on arcturus really is 2-BM.
It fails on something measured rather than imagined: arcturus holds its
address by DHCP (`proto dhcp` on the default route), so the identity rests
on a lease. It also breaks the first time a beamline calls from a second
host, which it will, since IOC and detector machines are separate.

**What tokens do and do not enforce here.** They separate beamlines, and
that separation is real: `/home/beams/2BMB` and its sibling homes are
distinct accounts with distinct permissions, so one beamline cannot read
another's token. They do not separate a beamline's own two clients, for
the reason in decision 5. Tokens are enforcement across the boundary that
exists and convention within it.

**A thinker needs a fifth, and not from any beamline's home.** It is the one
client that is not at a beamline, so it cannot read `/home/beams/2BMB` and
should not be given something that can. Its token belongs to the account it
actually runs under, which moves with it if it later moves to a host with a
GPU. That is one more subject in `subject_bindings` and no new machinery.

**What is given up.** Revocation. `jwt_token_verifier` says JWT access
tokens have none natively and the mitigation is a short TTL, which without
a token endpoint nothing re-mints. So tokens are long-lived and rotated on
a schedule over the NFS share, and a revocation is regenerating the keypair,
which invalidates all four at once. At four clients that is minutes. The
upgrade path is real: point `jwks_url` at a provider instead and nothing in
the keeper changes.

## The installation, as it now stands

Every placement below is measured rather than argued. What remains open is
named at the end rather than smoothed over.

```
                        lyra  164.54.113.45   routable, internet
                     ┌────────────────────────────────────┐
                     │  keeper + Postgres                 │
                     │  JWKS on loopback, the signer       │
                     │  thinker, while inference is        │
                     │  deterministic and pins it nowhere  │
                     └───────────────▲────────────────────┘
                                     │  HTTPS only, and every
                                     │  arrow points this way
        ┌────────────────┬───────────┴────┬─────────────────┐
        │                │                │                 │
   ┌────┴─────┐    ┌─────┴────┐    ┌──────┴───┐    ┌────────┴──┐
   │  2-BM    │    │  7-BM    │    │  19-BM   │    │  32-ID    │
   │ arcturus │    │ karman   │    │ radon    │    │ txmthree  │
   │ 2bmb     │    │ 7bmb     │    │ factuser │    │ usertxm   │
   └────┬─────┘    └─────┬────┘    └──────┬───┘    └────────┬──┘
        │ CA             │ CA             │ CA              │ CA
   ┌────┴─────┐    ┌─────┴──────┐  ┌──────┴────────┐  ┌─────┴────────┐
   │ tomdet   │    │ prandtl    │  │ orco          │  │ maxwell      │
   │          │    │ weber      │  │ hounsfield    │  │ txm4         │
   └──────────┘    └────────────┘  └───────────────┘  └──────────────┘
```

**Three of the four conductors sit on a routable host and 2-BM's does not.**
The pattern everywhere else is one routable machine per beamline, always the
screens machine, with the rest on the private subnet. A routable host reaches
a package index and finds no IOC by broadcast; a private host is the reverse;
no machine measured has both. So the routable one is where a client belongs:
installable directly, and still able to reach the hardware once given an
explicit Channel Access address list. 2-BM has no routable host identified, so
its software crosses into arcturus through the shared home, which is how that
beamline already works.

**Five principals, and the fifth is the one that needs a decision.** Four
beamline accounts, measured: `2bmb`, `7bmb`, `factuser`, `usertxm`, each with
one shared home that every host at that beamline mounts. A conductor and a
reporter at one beamline are one principal because the operating system does
not tell them apart. The fifth is whatever runs centrally.

**It should not be `2bmb`, and this is the sharpest thing the measurements
turned up.** That account is not only 2-BM's. It is the account on lyra, on
the bastion, and on every node of the compute cluster, all sharing one home.
A token written there at mode 600 is readable by anything running as that
account on a dozen machines, against three for each of the other beamlines.
Running the keeper's host and the thinker as `2bmb` would put the central
parts inside 2-BM's identity and widen that credential further.

So the central parts want an account of this system's own. Whether the one
that exists is facility-wide or per beamline decides whether it solves this or
quietly merges four principals into one, and that is a question for whoever
created it rather than one a measurement answers.

**What the ladder proves, given the above.** Step 1 is now four slugs, four
conductor hosts, five principals and a set-only procedure walked at each, and
nothing in it is blocked by a measurement any more. What blocks it is the
keeper being installed on lyra and `conduct()` becoming durable, which is the
critical path this file already names.

**Still open, and none of it is measurable from here:** who administers
lyra's backups; whether the central service account is facility-wide or per
beamline; whether the generically named beamline account is used outside its
beamline; and whether a write crosses between beamlines the way a read does,
which is gated by IOC access security and should be tested by staff on a
record chosen for it.

## What is needed before any of this is written down

Three of the original five are now answered by measurement on arcturus and
are recorded above: the engine at 2-BM, network reachability, and whether a
hosted identity provider is possible. What is left:

1. **The instrument list, answered.** The facility's internal index names
   them: 2-BM micro-tomography; 7-BM high-speed imaging and
   micro-tomography; 19-BM micro-CT; 32-ID projection microscope,
   nano-imaging, micro-CT and high-speed imaging. So 32-ID is four, and the
   earlier reading of this table was wrong twice: 7-BM's radiography and
   32-ID's transmission X-ray microscope are not what the index calls them.
   Eight instruments across four beamlines, which changes no decision here,
   because decision 2 makes the beamline the unit.
2. **Engine and store for the other three beamlines.** 2-BM is measured.
   The rest sorts instruments into engineless and not.
3. **Answered: `lyra`, with two asks attached.** Routable at
   164.54.113.45, reached by all four beamlines, reaches all nine
   beamline machines itself, and has internet egress for installing.
   RHEL 8.10, 8 cores, 38 GiB.

   **`tocai` is better hardware and was refused on coupling.** 32 cores,
   93 GiB, 79 GiB free against lyra's 17, RHEL 9.8, and Docker already
   present. It is also the bastion every one of these measurements was
   taken through. A keeper that fills its disk or pins its CPU takes out
   SSH to the whole facility, including the way in to fix it.
   **Generalisable: when the best-resourced host is the one everything
   else depends on, its spare capacity is not spare.**

   The two asks are for whoever administers lyra: **17 GiB free on the
   root filesystem** is where Postgres data has to live, because
   `/home/beams0` is NFS and a database does not belong there; and
   **Docker is absent**, so the compose arrangement needs it installed
   or a native Postgres instead. Neither blocks, both are worth asking
   before rather than after.

   What is still unanswered is the half that was never a measurement:
   **who administers its backups.**
4. **Answered for all four, and one answer is worth a second look.** Each
   beamline runs as its own account out of its own NFS home:

   | Beamline | Account | Home |
   | --- | --- | --- |
   | 2-BM | `2bmb` | `/home/beams/2BMB` |
   | 7-BM | `7bmb` | `/home/beams/7BMB` |
   | 19-BM | `factuser` | `/home/beams/FACTUSER` |
   | 32-ID | `usertxm` | `/home/beams/USERTXM` |

   **Decision 5's premise was checked against all four rather than
   assumed, and it holds**: one service account per beamline, four in
   all. 32-ID carries an older second account, retired and unused, which
   would have made it the exception had it still been live. That is the
   case decision 5 named as the one to watch for, and it did not happen.

   So the boundary decision 7 rests on holds, with one caveat. **19-BM's
   account names no beamline.** The other three are recognisably a
   beamline's account; `factuser` is a generic name, and if it is used
   anywhere else at the facility then one principal maps to more than one
   beamline and the boundary is weaker there than the table suggests.
   Worth asking before a token is issued to it.

   **Every beamline's hosts share one home.** A key installed on one host
   was already present on the others at 19-BM, 7-BM and 32-ID. That is
   decision 5 in the concrete: one account across three hosts and so one
   principal, which is the arrangement that makes a per-client
   distinction unenforceable rather than merely unmodelled.

5. **Answered for 32-ID and predicted for the rest by a pattern that
   holds at every beamline measured.** Each has exactly one routable host
   and it is always the screens machine:

   | Beamline | Routable | Private |
   | --- | --- | --- |
   | 2-BM | not identified | arcturus, tomdet |
   | 7-BM | karman `164.54.107.39` | prandtl, weber |
   | 19-BM | radon `164.54.129.35` | orco, hounsfield |
   | 32-ID | txmthree `164.54.102.6` | maxwell, txm4, ioc32idc02 |

   At 32-ID the routable host is the one a conductor should run on, and
   the reason generalises. It reaches the internet, so software does not
   have to cross a boundary to get there the way it does at 2-BM, and it
   still reaches the IOCs given an explicit Channel Access address list,
   because it finds none by broadcast. The private hosts are the mirror
   image: native Channel Access and no internet.

   **Generalisable: reaching the hardware and reaching a package index
   are separate properties, and the host with both may not exist.** What
   is measured at 32-ID and only inferred at 7-BM and 19-BM is the
   internet half; the subnets are measured everywhere.

6. **A GPU host, answered, and it is not the one this plan named.** There
   are five compute nodes carrying twelve A100 cards, not one, and two of
   them have working drivers today, the larger with four cards. So decision
   4's second row has a home now rather than after a request. `tomo1` is the
   node written up in most detail and the one that does not work: its driver
   was installed without the hook that rebuilds a kernel module, so the
   modules on disk belong to a kernel that is gone. All five share that
   omission and the two that work do so only because they have not been
   rebooted, which makes the fleet's health a snapshot rather than a
   property. What is still a request with lead time is privilege: loading a
   driver needs root, the working account has none, and that ask is already
   open.
7. **Whether the shared-home distribution path carries model weights.**
   Sound for a conda environment, untested for tens of gigabytes, and a
   question about quota and first-read throughput rather than about
   mechanism. Take it before weights are moved rather than after.
8. **Run at all four**, and it overturned the
   reason this question gave for itself. The claim was that a sweep cannot
   be run from another beamline because Channel Access does not route
   between them. **Measured 2026-09-29: it does.** Given an explicit
   address list, a 32-ID workstation reads 2-BM's rotation stage and a
   2-BM workstation reads 32-ID's rotation stage, camera and sample
   stack, across sectors and not through a gateway.

   **What the first measurement established was narrower than what was
   written down.** Broadcast does not cross a sector, so a client with
   default settings sees its own beamline and nothing else. That is the
   default address list doing the work, not the network, and the same
   thing happens one level down: broadcast does not cross between the
   routable and private subnets inside one beamline either, so the wrong
   workstation at the right beamline looks exactly like the wrong
   beamline. Nothing answers, and the two cases are indistinguishable
   without knowing the subnet a host sits on.

   So a register could in principle be swept centrally. It is still
   better swept at its own beamline, because somebody has to know which
   host serves what, and that is local knowledge either way. All four
   sweeps have been taken and all four registers are confirmed, at five
   rows, three, three and sixteen.

   **The two rows 19-BM's register does NOT have are the useful result.** 19-BM is in
   commissioning, and asked for its sample axes the acquisition software
   returns `TODO_SAMPLE_X` and `TODO_SAMPLE_Y`. Neither contains a `.` or
   a trailing `:`, so both satisfy the reference rule and the loader
   accepts them as devices. **A register can be well formed, confirmed by
   the same technique as every other row, and name nothing at all.** The
   rule checks the shape of a reference and cannot check that anything
   answers to it, so the sweep now reads every answer back before writing
   it down. That is one extra call per device and it is what kept two
   fictions out of the tree.

   **The security half of this belongs to decision 7 and is worse.** That
   decision reasons that tokens separate beamlines and the separation is
   real. It is real at the API. At the control layer the boundary is a
   default configuration, and any process that can set two environment
   variables is outside it. Reads are measured to cross. Writes are not
   tested, are gated by IOC access security, and should be tested by
   staff on a record chosen for it, because a write that succeeds moves
   hardware.

   19-BM starts no control software at boot, so an idle beamline and an
   unreachable one look the same. It was running when its survey was
   taken, but an empty result there needs that ruled out before it is
   believed.
