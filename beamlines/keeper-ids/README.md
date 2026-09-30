# The keeper id records

Two EPICS records that say which piece of keeper work a scan belongs to, and
the service that puts them at a beamline without changing anything the
beamline owns.

A conductor writes both before it starts a scan. A reporter reads them back
when the scan ends, and files the run and the dataset against the step they
name. A scan carrying neither is one somebody ran by hand, which is ordinary
and is ignored rather than held.

## Why this exists at all

TomoScan has no idea this system exists. Nothing in its base template, or in
any station's, carries a reference to an execution or a step, so a finished
scan says what it did and not what asked for it. These two records are the
join, and they have to come from somewhere.

## Three ways to get them onto a beamline

`records.db` is the artefact for all of them. Only the loader changes, which
is why there is one file rather than three.

| | what loads it | what it costs | what it buys |
| --- | --- | --- | --- |
| **a** | `softIoc`, as a service of ours | a second process to supervise | needs no restart of anything, so it can be done with users on the floor |
| **b** | a `dbLoadRecords` line in the station's `st.cmd` | one IOC restart, so it waits for a clear floor | one lifecycle instead of two |
| **c** | merged into `tomoScan.template` upstream | a release, and every station updating | the Python class can write the ids into the HDF5 |

**This directory is route (a).** It is the only one compatible with a
beamline in use, and it is a step rather than a destination.

Route (c) is the end state, and the difference is not convenience. Under (a)
and (b) the link from a dataset to the step that produced it exists only in
the keeper, so a file separated from the keeper cannot say where it came
from. Under (c) the ids are written into the data file and it is
self-describing.

## Installing

```bash
BEAMLINE=2-bm P=2bmb: R=TomoScan: CONTROL=2bmb:TomoScan:ServerRunning ./install.sh
```

The macro split is `$(P)$(R)` because that is what the TomoScan templates
use, so route (b) is later a `dbLoadRecords` line and not a rewrite.

`CONTROL` names a record at the same beamline that must answer. It is not
optional and it is not a convenience: the script's job is to refuse if either
id record is already served, and **an absent record and an unreachable
beamline fail identically**. Without a control that answers, a silent record
proves nothing, and the one thing worse than not installing this is
installing a second server for a name something else already has. Two servers
for one name is the fault 19-BM has on every motor, and here it would file
scans against the wrong work rather than merely read a stale number.

## After installing

A client on the same host as the IOC needs `127.0.0.1` in its
`EPICS_CA_ADDR_LIST` to see it. Beamline address lists are written to find
beamline IOCs and generally do not have it, so the conductor's and reporter's
environment may need it added. The install script checks that the records
answer from where it runs, which catches this, and says so when it fails.

## What this does not do

It does not edit the beamline's IOC, its startup script or its templates.
That is the whole reason this route exists.

It does not survive a restart with its values, deliberately. There is no
`PINI` and no autosave, so both records come back empty. A value that
outlived a restart would be a real, well formed id belonging to work this
system has lost track of, and a reporter reading it would attribute a scan
to the wrong step. `records.db` says more about that choice.

## What checks this

`tests/test_the_keeper_id_records_agree.py`, in the tree's own tier rather
than in either project. The record names are spelled in three places that
never meet: here, in the conductor's engine adapter and in the reporter's
record source. Each project's suite enumerates only its own directory, so a
rename in one of them leaves the other two alone with every lane green.
