# Where each part runs

*One installation, four beamlines, and the rule that decides what sits where.
Nothing is deployed yet. This is the shape the four projects are being pointed
at, with what has been measured marked as measured.*

## The rule

**Each part sits at the thing it cannot move away from.** That is the whole of
it, and it answers every row below without a separate argument per project.

Stating it as a rule rather than as four placements matters, because one of the
four is not pinned by anything and would otherwise read as though it were.

## The shape

```
  beamline networks: Channel Access and 0MQ, local only
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │     2-BM     │ │     7-BM     │ │    19-BM     │ │    32-ID     │
  │  micro-CT    │ │  radiography │ │ commissioning│ │  HSI and TXM │
  ├──────────────┤ ├──────────────┤ ├──────────────┤ ├──────────────┤
  │  EPICS IOCs  │ │  EPICS IOCs  │ │  EPICS IOCs  │ │  EPICS IOCs  │
  │  conductor   │ │  conductor   │ │  conductor   │ │  conductor   │
  │  reporter    │ │  reporter    │ │  reporter    │ │  reporter    │
  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
         │                │                │                │
         └────────────────┴───────┬────────┴────────────────┘
                                  │
                   HTTPS, one credential per beamline
          measured: 10.54.113.0/24 reaches 164.54.113.0/24
                                  │
                                  ▼
                  ┌───────────────────────────────┐
                  │  central host, not tomo1      │
                  │                               │
                  │    keeper      REST and MCP   │
                  │    Postgres    the event log  │
                  └───────────────────────────────┘
                                  ▲
                                  │  a thinker arrives, reads once,
                                  │  answers once, and is gone
```

Everything above the line is local by necessity. Channel Access does not route
and a document subscription has no offset to come back to, so only HTTPS
crosses. Every arrow points the same way: a client dials the keeper and the
keeper never dials back.

The thinker is drawn arriving rather than as a box, because it is the only one
of the four that is invoked rather than run. It is handed one question, reads
once, answers once and exits.

## What pins each part

| Part | Where | What pins it there |
| --- | --- | --- |
| keeper | one central host, on the routable subnet | its database |
| conductor | at the beamline, one per beamline | Channel Access does not route |
| reporter | at the beamline, or inside the engine's own process | a subscription is local and keeps no offset |
| thinker | wherever it is invoked | nothing of its own |

The fourth row is a different kind of claim from the first three, and the
column exists so that difference is visible. The keeper, the conductor and the
reporter are each held somewhere by something physical. A thinker needs network
access to the record and whatever does the thinking, and nothing else: no
database, no queue, no inbound port.

**Not `tomo1` for the keeper.** It is a two-GPU compute node, and a database
sharing a host with reconstruction jobs is a bad trade for both.

## The thinker, and what actually decides where it goes

A thinker has no home of its own. It inherits one from whatever sits behind its
inference seam, which is a dotted path to something the deployment writes.

```
   deterministic   Inference ──► pure Python    nothing pins it
   local weights   Inference ──► a GPU host     the weights pin it
   hosted model    Inference ──► HTTPS          egress pins it
```

**Today the first row is where this sits, so the invoker decides.** Nothing
invokes a thinker on its own yet, which means placement is downstream of a
question that is still open. A person at the central host runs it, so that is
where it runs.

**The second row is the near-term intent, and it has a home already.** The
facility runs a five-node compute cluster carrying twelve A100 cards between
them, and two of those nodes have working drivers today. So a thinker with
local weights does not wait on anything: the largest of them has four cards and
answers from a beamline.

The one node that is written up in most detail is the one that does not work,
which is worth knowing before it gets chosen by default. Its driver was
installed without the hook that rebuilds a kernel module, so the modules on
disk belong to a kernel that is gone; the cards are still on the bus and the
fault is entirely software. The same omission is present on all five, and the
two that still work do so only because they have not been rebooted onto a newer
kernel. So the fleet's health is a snapshot rather than a property.

**The constraint is privilege, not hardware.** Loading a driver needs root, the
working account has none worth the name, and a request for it is already with
the people who administer those machines. That is the thing to track.

One measurement is still missing and should be taken before weights are moved
rather than after: the distribution path this facility uses, a conda
environment under a shared home, is sound for a package and untested for tens
of gigabytes.

Two host questions therefore run in parallel, and they want opposite
properties. The keeper wants durability away from compute jobs. A thinker with
local weights wants the compute.

**A thinker is not per beamline, but a strategy may be.** There is no beamline
setting, deliberately: a thinker is handed an execution and the record says
where that work ran. So if micro-CT and a transmission X-ray microscope want
different thinking, that is one configuration file per strategy, chosen by
whoever invokes, not one installation per beamline.

## Who each part is when it arrives

The keeper identifies a caller as a principal. The question is how many there
are, and the answer is a rule rather than a number.

**One principal per operating-system account that can hold a credential.**

| | Separate accounts | Principals |
| --- | --- | --- |
| a conductor and a reporter at one beamline | no, both run as the beamline's service account | one, shared |
| the four beamlines | yes, four service accounts | four |
| a thinker, wherever it runs | yes, its own host and account | one of its own |

A conductor and a reporter at one beamline are not told apart, and that is
deliberate rather than an omission. They run as the same account and read the
same home, so whatever file one uses to prove itself the other can read.
Separating them in the record while the operating system does not separate them
would state a distinction that nothing enforces.

The thinker is the first case where per-account and per-beamline come apart. It
is not at a beamline, so the operating system does separate it, and the same
rule that merges the other two gives it one of its own.

**What this costs.** You cannot ask the record which of a beamline's two
clients did something. If that is ever wanted, the fix is not a change here: it
is giving them different accounts. Record granularity follows credential
granularity, and credentials are the facility's to shape.

**Adding the reporters later adds no principals**, which follows from the rule
and is worth knowing in advance.

## The one artifact with no home

Two of the projects resolve part of their behaviour through a dotted path to
something a site writes. A conductor names the thing that hands back a ready
engine, and a thinker names the thing that hands back whatever does the
thinking. Both documentation pages reach for a package named after a beamline,
and that package is in no repository here, built by no lane and covered by no
suite.

That is by design. A model name, a temperature and a retry policy are arguments
to something a site owns, and neither project will grow settings for them. But
it means every deployment has a fifth artifact beyond the four installs, it is
the one nothing in this tree can test, and a local-weights adapter is the first
substantial thing to land in it.

## Which beamlines, and what is known of each

Four, and they are not in the same state. What decides whether a beamline can
use a path is what acquisition software is installed there, and that has been
established at one of them.

| Beamline | Instruments named | Acquisition software | Paths open today |
| --- | --- | --- | --- |
| 2-BM | micro-tomography | surveyed: tomoscan, and nothing this system can read documents from | driving, not recording |
| 7-BM | high-speed imaging, micro-tomography | not surveyed | unknown |
| 19-BM | micro-CT, in commissioning | documented in detail, not yet surveyed | unknown |
| 32-ID | projection microscope, nano-imaging, micro-CT, high-speed imaging | not surveyed | unknown |

The instrument lists are the facility's own, taken from its internal index
rather than from anybody's memory. "Not surveyed" is an honest entry and not a
placeholder: it means nobody has asked the beamline itself.

19-BM is the odd row. It is documented in more detail than any of the others,
down to its two control hosts, its motor assignments and its safety interlock
bridge, and it runs the same acquisition software as 2-BM. What is missing is
only the survey, and there is a plausible reason it could not be taken
remotely: that beamline starts no control software at boot, so a quiet address
and an idle beamline look identical from outside.

**Channel Access does not route between beamlines, and this is now measured
rather than asserted.** From a 2-BM workstation, 2-BM's own records answer and
no other beamline's do, including through a neighbouring sector's gateway,
which answers for facility-wide records and not for that sector's instruments.
That is the reason a conductor lives at its beamline stated as an observation:
a central one could not see the hardware.

**The unit is the beamline and not the instrument.** Where two instruments sit
at one beamline they share a front end, an insertion device and a
monochromator, so they get one conductor and one claim ledger between them.
An instrument is a partition inside a beamline, not a thing that gets its own
copy of the software.

## What is not proven

Worth reading before treating the picture above as working software.

**No reporter can run at any of these beamlines yet.** Its only input is the
document stream an engine publishes, and none of the four runs one.
2-BM was measured on its own workstation: the installed acquisition package
publishes no documents at all, and none of the usual engine, control or store
libraries is present.

**A pursuit cannot turn where there is no engine.** Composing a round produces a
procedure of exactly one run step, and a run hands a routine to an engine. So
the half of the conductor that has been driven against real hardware, the
control seam over Channel Access, is the half a pursuit cannot currently use.

**Three of the four beamlines have been measured for nothing**, which the
table above says row by row. The descriptor rule in
[`beamlines/README.md`](https://github.com/open-cora/cora/blob/main/beamlines/README.md)
is what keeps a guess from being written down as a fact. That is why this site
carries a page for [2-BM](2-bm.md) and none for the others: a page appears when
somebody has looked.
