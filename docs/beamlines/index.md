# Where each part runs

*One installation, four beamlines, and the rule that decides what sits where.
This is the shape the four projects are pointed at, with what has been measured
marked as measured. What is deployed today is read back from the hosts rather
than remembered here: the keeper, and a conductor at each of the four. The
simulators a conductor drives are at 2-BM alone.*

## The placement rule

**Each part sits at the thing it cannot move away from.** That is the whole of
it, and it answers every row below without a separate argument per project.

Stating it as a rule rather than as four placements matters, because one of the
four is not pinned by anything and would otherwise read as though it were.

## Where the parts sit

```
  beamline networks: Channel Access and 0MQ, local only
  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
  │     2-BM     │ │     7-BM     │ │    19-BM     │ │    32-ID     │
  │  micro-tomo  │ │  radiography │ │ commissioning│ │  HSI and TXM │
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
                                  │  a thinker waits here for a
                                  │  question, and answers it
```

Everything above the line is local by convention rather than by necessity.
Channel Access does not find an IOC across a sector by broadcast and a document
subscription has no offset to come back to, so in practice only HTTPS crosses. Every arrow points the same way: a client dials the keeper and the
keeper never dials back.

The thinker is drawn on the arrow rather than as a box at either end, because
it is the only one of the four whose placement nothing physical decides. It
holds a request open at the keeper until a question is there, answers it, and
asks again.

## Placement, part by part

| Part | Where | What pins it there |
| --- | --- | --- |
| keeper | lyra, on the routable subnet | its database |
| conductor | at the beamline, one per beamline | latency and blast radius, not the network |
| reporter | at the beamline, or inside the engine's own process | a subscription is local and keeps no offset |
| thinker | lyra, beside the keeper | nothing of its own, so the keeper it dials |

The hosts are now named rather than described, and the pattern that names them
is exact at every beamline measured: **one routable machine and the rest on the
beamline's own private subnet, and the routable one is always the screens
machine.**

A conductor is placed at all four, and each host below was chosen by reading
that beamline's own registered records from it rather than by applying the
pattern. The column says what was measured from the host, which is a separate
question from whether a conductor runs there, and all four run one today. Two
of them do not behave the way the pattern predicts.

| Beamline | Conductor | Reaches its records by | Reaches a package index |
| --- | --- | --- | --- |
| 2-BM | arcturus | broadcast, the IOCs are on it | no, built elsewhere |
| 7-BM | karman | broadcast | yes |
| 19-BM | radon | broadcast | yes |
| 32-ID | txmthree | an explicit address list | yes |

Routable and private differ in two ways. A routable host reaches a package
index; a private one does not, and gets its software through the beamline
account's shared home. So a routable host is the easier place to put a
client, and 2-BM has none, which is why its conductor is built on another
machine and run from the shared home.

**Channel Access does not divide as neatly, and the measurements say so.**
karman and radon are both routable and both find their beamline's records by
broadcast with no address list at all, which the earlier claim here said they
could not. karman has a second interface on a private subnet, so it is not
even surprising; radon has only its routable address and finds them anyway.

**32-ID is the one that behaves as described**, and it is worth following
because it shows what the address list is for. txmthree finds nothing by
broadcast. An address list naming maxwell, the obvious private host, also
finds nothing, because maxwell does not serve those records: it only sees
them the same way. `cainfo` names the actual servers, `txm4` and
`ioc32idc02`, and an address list naming those two reads every record.

The lesson generalises past this beamline. **Ask a record which server
answers for it rather than assuming the host you can see it from is the host
that serves it.** The wrong address list and no address list fail the same
way.

The fourth row is a different kind of claim from the first three, and the
column exists so that difference is visible. The keeper, the conductor and the
reporter are each held somewhere by something physical. A thinker needs network
access to the record and whatever does the thinking, and nothing else: no
database, no queue, no inbound port. That stays true now that it waits for
work, because it waits on a request it made.

**Not `tomo1` for the keeper.** It is a two-GPU compute node, and a database
sharing a host with reconstruction jobs is a bad trade for both.

## Where a thinker runs

A thinker has no home of its own. It inherits one from whatever sits behind its
inference seam, which is a dotted path to something the deployment writes.

```
   deterministic   Inference ──► pure Python    nothing pins it
   local weights   Inference ──► a GPU host     the weights pin it
   hosted model    Inference ──► HTTPS          egress pins it
```

**Today the first row is where this sits, so nothing decides.** A thinker now
finds its own work, so it is a service rather than a command somebody types,
and the question of who starts it is settled. Deterministic inference pins it
nowhere, which leaves the central host as good as anywhere and better than
most: the keeper is the only thing a thinker attaches to, and there that
attachment never leaves the machine.

So that is where it goes, and the measurements behind the choice are worth
keeping because the second row will reopen the question. The central host has
spare capacity and idles, its certificate already covers a client dialling it
from the same machine, the thinker's credential is already sitting there, and
it reaches the compute cluster for the day the weights arrive. What it costs
is that a client sharing a host with the server it polls can degrade it for
every beamline, which is the argument that pushed the conductors out and is
outweighed here only because a thinker is one process holding one socket.

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
where that work ran. So if micro-tomography and a transmission X-ray microscope want
different thinking, that is one configuration file per strategy, chosen by
whoever invokes, not one installation per beamline.

## Identity: one principal per account

The keeper identifies a caller as a principal. The question is how many there
are, and the answer is a rule rather than a number.

**One principal per operating-system account that can hold a credential.**

| | Separate accounts | Principals |
| --- | --- | --- |
| a conductor and a reporter at one beamline | no, both run as the beamline's service account | one, shared |
| the four beamlines | yes, four service accounts | four |
| a thinker, wherever it runs | yes, its own host and account | one of its own |

The four accounts are measured rather than assumed: each beamline runs as one
account out of one shared home, and every host at that beamline mounts it. One
of the four names no beamline, which is worth knowing before a credential is
issued to it, because a generic account used anywhere else maps one principal
to more than one beamline.

**One account reaches much further than its beamline, and that is the finding
this section turns on.** 2-BM's account is also the account on the central
host, on the bastion, and on every node of the compute cluster. Its home is
the same home on all of them. So a token written into that home at mode 600 is
readable by anything running as that account on a dozen machines, where the
other three beamlines' tokens are readable on three each.

That is not an argument against the token arrangement. It is an argument
against the central parts borrowing a beamline's account, and the argument is
narrower than it first looks, which is worth being exact about because the
install was built against the wide version.

**Who a caller is in the record does not come from the account.** It comes
from the subject inside the token, so a thinker running under a beamline's
account is still its own principal with its own actor, and nothing it does is
attributed to that beamline. The earlier claim that it would be is wrong.

**What the account decides is who can read the credential**, and that is a
real cost rather than a theoretical one. It is also the half the installation
answered: the central host keeps its secrets on local disk with the directory
closed to everyone else, not in the shared home, so reading them needs that
account on that one machine rather than on a dozen. What remains true is that
anybody who has it there can read the signing key and mint a token for any
principal, which is the case with or without a thinker beside it.

A service account belonging to this system rather than to a beamline is still
the shape that fits, and whether one exists facility-wide or per beamline
decides whether it helps or quietly merges four principals into one.

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

## The fifth artifact: the adapter package a site writes

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

## The four beamlines

Four, and they now open the same paths, which was not true when this page was
written. What decides whether a beamline can use a path is what acquisition
software is installed there, and that has now been established at all four by
asking each of them.

| Beamline | Instruments named | Acquisition software | Paths open today |
| --- | --- | --- | --- |
| 2-BM | micro-tomography | surveyed: tomoscan, and nothing this system can read documents from | driving and recording |
| 7-BM | high-speed imaging, micro-tomography | surveyed: tomoscan, as at 2-BM | driving and recording |
| 19-BM | micro-tomography, in commissioning | surveyed: tomoscan, two sample axes unconfigured | driving and recording |
| 32-ID | projection microscope, nano-imaging, micro-tomography, high-speed imaging | surveyed at micro-tomography: tomoscan, as at 2-BM | driving and recording |

The instrument lists are the facility's own, taken from its internal index
rather than from anybody's memory, with one word normalised: that index calls
the same technique micro-CT at some of these beamlines and micro-tomography at
others, and these pages say micro-tomography throughout. A beamline's own
manual may well say micro-CT, and it means this. "Not surveyed" is an honest
entry and not a placeholder: it means nobody has asked the beamline itself.

19-BM is the odd row, and it is odd for a different reason than it used to
be. It is documented in more detail than any of the others, down to its two
control hosts, its motor assignments and its safety interlock bridge. What
its survey wrote down is sixteen motors, the largest register here. It is in commissioning, and asked for its
sample axes the acquisition software returns two placeholder strings that
name no record at all, which is a more instructive answer than a full
register would have been and is set out on its own page. That beamline also
starts no control software at boot, so a quiet address and an idle beamline
look identical from outside, and an empty result there needs ruling out
before it is believed.

32-ID was the same row until it was surveyed, and what the survey found is on
its own page. The one part worth repeating here is that its two workstations
have opposite properties, one routable with an internet route and no way to
find an IOC by broadcast, the other on the beamline network with the reverse
of both. A first attempt from the wrong one found nothing and read as the
beamline being unreachable.

**Channel Access does not find another beamline by broadcast, and it reaches
one perfectly well when told where to look.** Both halves are measured. From a
2-BM workstation with default settings, 2-BM's own records answer and no other
beamline's do, including through a neighbouring sector's gateway, which serves
facility-wide records and not that sector's instruments. But given an explicit
address list, a 32-ID workstation reads 2-BM's rotation stage and a 2-BM
workstation reads 32-ID's, both across sectors and neither through a gateway.

**So the earlier reading of that measurement was too wide, and this page
carried it.** It said a conductor lives at its beamline because a central one
could not see the hardware. A central one could. What the first measurement
established is narrower: the default address list is what keeps a beamline's
clients looking at their own beamline, and that is a configuration rather than
a boundary.

The rule survives on the reasons that actually hold. A conductor at its
beamline talks to its IOCs over one hop, and one that dies takes down work at
one beamline rather than at four. Those are good reasons and they are not the
reason this page used to give.

**Reads cross; writes are untested.** Everything above is a read of a
description field. Whether a write crosses is a separate question, gated by
IOC access security, which can refuse per record. It should be tested by
beamline staff on a record chosen for the purpose, because a write that
succeeds moves hardware.

**The unit is the beamline and not the instrument.** Where two instruments sit
at one beamline they share a front end, an insertion device and a
monochromator, so they get one conductor and one claim ledger between them.
An instrument is a partition inside a beamline, not a thing that gets its own
copy of the software.

## Which adapter fills which seam

A beamline's `adapters.toml` says what software reaches its hardware, the way
its `devices.toml` says what hardware exists. All four currently carry the same
register, which is worth stating plainly because it is the reason one table
serves here:

| Slot | Adapter | What it fills |
| --- | --- | --- |
| `driving.control_system` | `epics_control` | the conductor's `Adjusting`: moves one record and verifies it arrived |
| `driving.scan_engine` | `tomoscan_engine` | the conductor's `Running`: hands a routine to a TomoScan server |
| `recording.deliveries` | `tomoscan_records` | where a reporter hears a scan from, which here is Channel Access rather than a document stream |
| `recording.data_format` | `dxchange_hdf5` | the reporter's `Describing`: opens the file and measures it |
| `recording.store` | `none` | the reporter's `Locating`, unfilled: these deployments have no data store |
| `processing.recon_engine` | `none` | nothing, and no seam for it exists |
| `processing.data_transfer` | `none` | nothing, and no seam for it exists |

`none` here is a measured absence rather than an open question, which is the
distinction `unsurveyed` carries and no slot currently needs.

**Four adapters are written and deployed nowhere**, and they are the document
path and the store. `bluesky_engine` fills the same seam as `tomoscan_engine`
and has never been run; `zmq_subscription` and `bluesky_documents` are the
delivery and the translation behind it; `store_http` fills `Locating` and waits
on a store to point at. None of that is missing work. It is work finished
against a seam no beamline here has yet had a reason to use.

**The two `processing` slots are different in kind** and the register is
deliberately able to say so before either exists. Reconstruction and data
transfer have no Protocol anywhere in this tree, so a name in either slot would
resolve to nothing; the adapter test refuses any value but `none` or
`unsurveyed` there, which is what makes it safe to list them at all.

What this table does not say is whether anything is running. That is a fact
about a host, it belongs to the rows above and to each beamline's own page, and
keeping the two apart is what stops them disagreeing.

## What is not proven

Worth reading before treating the picture above as working software.

**Two reporters run, at 7-BM and 19-BM.** This page said none ran anywhere,
and the correction it carried for a day said so more precisely. Both were
wrong. Re-measured 2026-10-05 by listing the user units on every host:

| Host | Beamline | `cora-reporter` |
| --- | --- | --- |
| karman | 7-BM | enabled, active, describing |
| radon | 19-BM | enabled, active, describing |
| arcturus | 2-BM | enabled, active, describing |
| lyra | the keeper's host, no beamline | installed, disabled |
| txmthree | 32-ID | enabled, active, describing |

Both now carry a describer, so a filed dataset says what is inside it and
not only where it is. 7-BM got one on 2026-10-05 and 19-BM a day earlier,
and each needs `h5py` in the reporter's own virtualenv, which the
`describe-hdf5` extra installs and a plain sync does not.

Both read TomoScan's records rather than a document stream, which is what
that source was written for: a reporter's only input used to be the documents
an engine publishes, and none of these four publishes any. 2-BM's workstation
bore that out, and a source that reads records removed the barrier.

The configuration limit behind it is gone too. Such a reporter registers an
address its engine already reported and never resolves a name, and the
`[store]` table used to switch filing and locating on together, so asking for
the first meant describing a store that is not there. Each half has had its
own switch since `e39244a`.

**The wrong claim is worth more here than the right one.** It came from a
measurement nobody dated, inside a section headed by what is not proven,
which is exactly where somebody looks before deciding what to deploy. It
survived a correction to the sentence beside it. Anything on this page
asserting what is installed where should be re-measured before it is acted
on, because the hosts change and the page does not.

**A pursuit cannot turn where there is no engine.** Composing a round produces a
procedure of exactly one run step, and a run hands a routine to an engine. So
the half of the conductor that has been driven at a beamline, the control
seam over Channel Access, is the half a pursuit cannot currently use.

**All four beamlines have now been surveyed**, which the table above says row
by row, and each has a page: [2-BM](2-bm.md), [7-BM](7-bm.md),
[19-BM](19-bm.md) and [32-ID](32-id.md). A page appears when somebody has
looked, and somebody now has at all four.

What the descriptor rule in
[`beamlines/README.md`](https://github.com/open-cora/cora/blob/main/beamlines/README.md)
keeps out is a guess written down as a fact, and the four registers are very
different sizes because of it: sixteen rows, five, three and three. The
largest is 19-BM's, and that beamline is also where the rule itself was
found wanting, because a reference can be checked for shape and not for
existence. Two further rows were offered there and name no record at all.
Every answer is now read back before it becomes a row.
