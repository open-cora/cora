# Expansion: four beamlines, and what that changes

Planning. `PLAN.md` is the single-beamline plan this revises; where the two
disagree, this one is later.

## What is being expanded to

| Beamline | Instruments named | State |
| --- | --- | --- |
| 2-BM | micro-tomography | operating |
| 7-BM | radiography with spectroscopy-alike enhancements; the internal docs also list high-speed imaging and micro-tomography | operating |
| 19-BM | micro-CT | commissioning |
| 32-ID | high-speed imaging, transmission X-ray microscope; the internal docs also list a projection microscope and micro-CT | operating |

The instrument count is not settled. The facility's internal index lists
more instrument pages than the four-plus-two above, so the first thing to
pin is what counts as an instrument here and which of those pages describe
one.

## The shape, drawn

Three views of the recommendation below: the topology, one beamline in
detail, and what a descriptor feeds.

```
  beamline networks: Channel Access and 0MQ, local only
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │     2-BM     │ │     7-BM     │ │    19-BM     │ │    32-ID     │
  │  micro-CT    │ │  radiography │ │ commissioning│ │  HSI + TXM   │
  ├──────────────┤ ├──────────────┤ ├──────────────┤ ├──────────────┤
  │  EPICS IOCs  │ │  EPICS IOCs  │ │  EPICS IOCs  │ │  EPICS IOCs  │
  │  engine      │ │  engine      │ │  engine      │ │  engine      │
  │  conductor   │ │  conductor   │ │  conductor   │ │  conductor   │
  │  reporter    │ │  reporter    │ │  reporter    │ │  reporter    │
  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
         │                │                │                │
         └────────────────┴───────┬────────┴────────────────┘
                                  │
                 HTTPS outbound, bearer + X-Principal-Id
                      reachability: UNCONFIRMED
                                  │
                                  ▼
                  ┌───────────────────────────────┐
                  │  central host, not tomo1      │
                  │                               │
                  │   apps/api     REST + MCP     │
                  │   Postgres     event log      │
                  │                one Policy     │
                  └───────────────────────────────┘
```

Everything above the line is local-network by necessity: Channel Access
does not route, and a subscription has no offset to come back to. Only
HTTPS crosses.

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
  ┌───────────┴───────────┐  acquire   ┌──────────────────┴──────────┐
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
     ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─  central AROC  ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─ ─
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
    └── reporter.toml ─── + token from env ─────► apps/reporter
          base_url, schemes, plan map                   (blocked: engine)
```

Only the first line works today. `principals.toml` does not exist yet, and
`reporter.toml` is blocked behind the engine question rather than the token
question.

## Two paths, and only one of them is gated on engines

This section is rewritten against `execution-topology`, a decision settled
in conversation the same day and not yet in the repo, which supersedes the
framing that the conductor is only a peer client. The correction matters
enough to state plainly: an earlier draft of this plan said expansion was
gated on engine coverage, and that is true of one path and not the other.

**The recording path is gated on engines.** `apps/reporter` reads the
documents an engine publishes. `spikes/tomoscan_adapter/FINDINGS.md`
measured the engine 2-BM-S runs and found no documents at all, no run
identity until a scan ends, and nothing to key a plan map on. So a
`reporter.toml` for that instrument configures a client that cannot
connect, which is why `PLAN.md` step 3 stopped.

**The driving path is not.** The conductor holds two seams and `Control`
needs no engine: a procedure walks over Channel Access at a beamline that
has never heard of an engine. No beamline in this set runs a queue manager,
so the engineless shape is the common one here rather than the exotic one.

```
   engineless    conductor --Control-->     EPICS       the conductor IS the engine
   bare engine   conductor --Acquisition--> RunEngine   it owns the writer slot
   managed       conductor --Acquisition--> RE Manager  it is one client of several
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
the word the same way. In the code, a deployment is one AROC installation.

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
layer does not save it either: `spikes/access_security/FINDINGS.md` found
the IOC-side gate can refuse a write per record in under a millisecond and
**cannot tell two processes on one workstation apart**.

**Recommendation: one device register, one conductor and one claim ledger
per beamline. An instrument is a partition inside it, not a unit of its own.**

**The ledger does not cover a human.** It is in-process, so it cannot see
a scientist at their own session on the same beamline, which stays a second
writer whatever AROC does. `execution-topology` names that as the condition
under which a queue manager is adopted rather than built, and lists the
tripwires to watch for. One ledger per beamline is the right boundary for
the writers AROC runs; it is not a claim to arbitrate the ones it does not.

The partition needs no new descriptor field, which matters because of the
one rule. A device's `name` is this system's own label, authored here, so
`name = "TXM sample rotation"` carries the instrument without a column that
no AROC command accepts. The partition earns a real field on the day a
procedure descriptor needs to select by it, and not before.

## Decision 3: one installation, and the gap that decision carries

**Recommendation: one AROC installation serving all four beamlines.** Four
installations means four databases, four migration paths, four backup and
restore drills and four upgrade decisions, for a system with no users yet.
One installation also keeps actor ids and plan ids meaning one thing.

The cost has to be stated plainly, because it is not small.

**Authority has no resource scoping.** A permission is a `(principal,
command)` pair and nothing else. There is no subject, no beamline and no
instrument in it. `surface_id` is not the seam: it names the arrival
surface, HTTP or MCP, is derived from the process, and
`policy_authorize.py` says outright that it is accepted and not consulted,
because no aggregate models a surface.

So on one installation, a principal granted `FaultDevice` so that 19-BM's
reporter can report a fault may fault 2-BM's camera. Four installations
would get that isolation physically and for free.

Two things make the single installation defensible anyway. The pair shape
already prevents the worst version: permissions are not two lists, so
granting a principal one command grants it one command and not the cross
product. And at the control layer these beamlines have no mutual protection
today either, since the access gate the spike measured must be configured
per record to exist at all. AROC with unscoped authority is not a
regression on that.

**The trigger to revisit is a beamline team asking to be protected from
another beamline's principal.** At that point the choice is resource
scoping in Authority, a real domain change, or splitting the installation.
Record it, do not build for it.

## Decision 4: where each part runs

- **`apps/api` and Postgres: central, one host, reachable over HTTPS from
  every beamline.** Not `tomo1`: that is a two-GPU compute node with the
  driver unloaded, and a database sharing a host with reconstruction jobs
  is a bad trade for both.
- **`apps/conductor`: at the beamline, one per beamline.** Channel Access is
  a local-network protocol and a motor is not driven from a datacenter.
  That is the app's own stated reason for existing as a separate project.
- **`apps/reporter`: at the beamline**, because a subscription is local, or
  in the engine's own process, for which the README already has the recipe.

The open question is reachability. The facility's own notes put `tomo1` and
`tomodata1` on the routable 164.54.113.0/24 and the rest of that cluster on
10.54.113.0/24. Which network a beamline workstation sits on, and whether
it can open an outbound HTTPS connection to a central host, decides whether
this shape works at all.

## Decision 5: service accounts belong in the descriptor

Access holds **no name** for an Actor, and says why: "the actors this system
sees are service accounts, and a service account is named where it is
provisioned." An actor is a UUID and an on/off switch.

That leaves the map from a provisioned account to its AROC actor id with no
home inside the API, and the descriptor is its home for exactly the reason
the reporter's plan map is: it depends on which installation serves which
beamline, and nothing on the two records would tell them apart.

It also passes the one rule, because it has three consumers already:
`seed_devices.py --principal-id`, the conductor, and the reporter's
`X-Principal-Id`.

Two notes on the account itself.

**`svccora` is named for the sibling project, and is unused.** That it is
unused settles it: there is no migration to weigh against the name, so the
accounts to provision are named for this system instead, one per client,
`svcaroc-<beamline>-<client>`. It would not have broken
`test_no_sibling_project_vocabulary.py`, which matches `cora` on a word
boundary `svccora` does not offer and which scans `apps/api` only, but a
name carried through every descriptor and every log line for a system with
no other connection to the sibling is a cost with nothing on the other side.

**One actor per client, not one per beamline.** A beamline's conductor and
its reporter do different things and should be refused differently. That is
also the only granularity unscoped authority still gives you.

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

## What is needed before any of this is written down

1. **The instrument list**, settled: which of the internal docs' pages
   describe an instrument AROC would serve, and whether 32-ID is two or
   four.
2. **Engine and store per instrument**, which now sorts the instruments
   into engineless and not rather than blocking everything behind itself.
3. **Host computers**, per beamline, for the conductor and the reporter, and
   one candidate host for the central API and its database.
4. **Network reachability**: can a beamline workstation open an outbound
   HTTPS connection to that central host.
5. **Confirmation that per-client accounts can be provisioned** in the
   `svcaroc-<beamline>-<client>` shape, and how many that comes to once the
   instrument list is settled.
