# Findings

What building real ophyd devices against a soft IOC over real Channel
Access actually showed. Everything below is printed by `observe.py` or
read out of the installed package, and the two are marked apart wherever
it matters.

Run against ophyd 1.11.2, caproto 1.3.0, pyepics 3.5.10, Python 3.13.

This spike exists to ask what an equipment model can honestly hold, before
one is written. Three questions went in, and a fourth came out of the
first three.

## The short version

**A device's name is a client-side fact and nothing at the facility knows
it.** The same motor is `station_sample_x` to one startup profile and
`tomo_sample_x` to another, both connected at once, and nothing rejects
either. The only handle the facility issues is the PV prefix.

**A fault is readable while it lasts and gone afterwards.** The alarm is
real, which is better than the TomoScan result. It is also current rather
than historical: it clears when the condition clears and leaves nothing
behind, so "was this device faulted during that run" cannot be answered
after the fact.

**The value path fails loudly and the alarm path fails silently.** With
the IOC dead, `get()` raises and `alarm_severity` returns the last number
it saw, with nothing in the call to say it is stale. A poller reports
faults that have ended, misses faults that have started, and keeps
reporting a fault for a device that no longer exists.

**The alarm is not in the reading.** `read()` carries `value` and
`timestamp`. Nothing that logs readings retains the alarm.

**Where one device stops is a client-side composition too.** Thirty
signals under one `Station`, arranged by three classes a profile author
wrote. The IOC publishes a flat namespace of prefixes and has never heard
of `Station`.

## 1. Identity is assigned in Python, not at the facility

`observe.py` builds the station twice, from the same class, against the
same IOC, under two names:

```
   ophyd name           'station_sample_x'
   same PV, 2nd profile 'tomo_sample_x'
   the PV               '2bmb:m1.RBV'
```

Both connect. Both work. Neither is more correct, and nothing anywhere
records that they are the same device. The name is the `name=` argument
a beamline's startup profile passes at construction, so it survives
exactly as long as that Python process and changes whenever somebody
edits the profile.

**The one facility-side label is `DESC`, and it does not hold.** The motor
record has one. It is served empty, and `observe.py` writes it over
Channel Access the way an operator would:

```
   motor DESC served    ''
   after an operator    'sample x translation'
```

Any client can write it, nothing enforces uniqueness, and it is free text.
It is a caption, not an identifier.

**What this costs AROC.** The external reference cannot be the ophyd name.
It has to be the PV prefix, `("epics-prefix", "2bmb:m1")` or the local
equivalent, because that is the only string two independent clients will
agree on. Note what that concedes: the prefix is a deployment's
configuration and an IOC can be rebuilt under a new one, so it is stable
in practice rather than guaranteed. It is still the best available, and
it is better than the TomoScan case, where the closest thing to a run
identity was an output file path.

That last comparison has since dated, and not in this spike's favour: 2-BM
added a `ScanUUID` after both spikes ran, so a tomography run there is now
named better than a device is here. See section 3 of
`spikes/tomoscan_adapter/FINDINGS.md`, which is the second reading of a
finding that changed.

## 2. The alarm is real, and it is current rather than historical

Driving the camera over its threshold and back:

```
   when                         value    severity  status
   before                       20.0     0         0
   while the camera is too hot  45.0     2         3
   after it cools               20.0     0         0
```

Severity 2 is MAJOR and status 3 is HIHI. This is the good news, and it
is a genuine improvement on the TomoScan finding, where four different
endings produced one status string and the outcome existed only in a
Python log line. Here the fault reaches a client.

It reaches a client **while it lasts**. The third row is the problem:
after the condition clears, the record holds nothing that says it ever
happened. There is no latch, no count, no timestamp of the last alarm.
A reporter that was not subscribed at the moment is told nothing, and a
reporter that restarts loses what it had.

This is the same shape as the TomoScan durability gap and the reporter's
own, and it is worth recognising as such rather than treating as new:
**the outcome is at-most-once, delivered only to whoever happened to be
listening.**

## 3. The alarm is not in the reading

```
   a reading carries: ['timestamp', 'value']
   alarm in the reading: False
```

`read()` returns value and timestamp. `describe()` returns source, dtype,
shape, units, control limits and precision, and no alarm field either.
So the alarm travels on the metadata of a monitor update and on nothing
that a document-shaped pipeline retains.

Anything built on `read()` has already discarded the fault by the time it
writes a row.

## 4. The client's cache lies, and only in one direction of failure

The sharpest result, and it was an accident before it was a measurement.
The camera is left in MAJOR alarm, the IOC is killed, and the same signal
is probed three times. Each probe reads the severity, then does a `get`,
then reads the severity again:

```
                     connected  sev before get  sev after get  get
      while_up       True       0               2              45.0
      while_down     False      2               2              raised ConnectionTimeoutError
      after_restart  True       2               0              20.0
```

Three separate ways to be wrong:

- **while_up.** The device is in MAJOR alarm. Asking `alarm_severity`
  without reading the value first answers 0. The cached metadata had not
  caught up, and nothing in the call says so.
- **while_down.** `get()` raises `ConnectionTimeoutError`, loudly and
  correctly. `alarm_severity` returns 2, silently, for a device that is
  not there. The value path and the alarm path disagree about whether
  this device can be reached, and only one of them tells you.
- **after_restart.** The stale 2 outlived the outage and a whole IOC
  process. It is cleared by the read, not by the reconnection.

**This is the inverse of the TomoScan sticky boolean, and worse.** There
the IOC's own record was wrong and stayed wrong until somebody cleared
it. Here the record is fine and the client's copy of it is wrong, which
means two reporters watching the same device can hold different opinions
about whether it is faulted, and neither is reading anything it could
check.

A poller built on `alarm_severity` therefore reports faults that have
ended, misses faults that have started, and keeps reporting a fault for a
device that has gone away. Every one of those failures is silent.

## 5. Where one device stops is a profile author's opinion

```
   components         ['sample_x', 'camera', 'experiment']
   signals beneath    30
   readings           5
   configuration      13
```

Twelve of the thirty signals appear in neither `read()` nor
`read_configuration()`. The nineteen under `sample_x` are the motor
record's fields, which ophyd's own `EpicsMotor` declares; the four under
`camera` and seven under `experiment` are components this spike wrote.

The tree is three Python classes. The IOC serves a flat namespace of
prefixed records and knows nothing about `Station`, so **ophyd does not
tell you where a device stops. It tells you where whoever wrote the
profile said it stops**, and section 1 already showed two profiles
disagreeing about the same hardware.

The one boundary both sides can see is the prefix.

## 6. Personal data is configuration here, and the obvious redaction is wrong

Seven of the thirteen configuration keys are a named person:

```
   station_experiment_user_name          station_experiment_user_email
   station_experiment_user_last_name     station_experiment_user_institution
   station_experiment_user_badge         station_experiment_proposal_number
                                         station_experiment_esaf_number
```

These are the records `tomoScan_2BM.template` declares, copied here for
that reason. Section 8 of the TomoScan findings called this a schema
rather than a risk, and `read_configuration()` is the method that hands
all of it over in one call.

The trap has a second side, which this spike found by falling into it.
The obvious redaction rule is to drop keys matching `user`. That also
drops:

```
   says user, is not  ['station_sample_x_user_offset',
                       'station_sample_x_user_offset_dir']
```

A motor's user coordinate offset is calibration, not a person. So
sweeping configuration wholesale stores a badge number, and redacting by
substring drops calibration. Neither is safe, and the only rule that
worked here selected by which sub-device declared the signal.

## 7. What this says about AROC's model

**The disposition model survives, and its external reference is decided.**
An Equipment context holding registered / faulted / recovered / retired
is recordable against this engine, and the reference has to be the PV
prefix for the reason in section 1.

What the engine hands a reporter is an alarm severity, and an alarm is
not a fault: MINOR alarms are routine and a device in one is usually
still usable. So the fault is the reporter's judgement and not a value
copied through, which is the same call a reporter already makes when it
picks one of Execution's three terminals. The severity itself should not
reach the record. On the record it invites a later reader to derive
faultedness from it, and that is a claim about hardware health this
system never made.

**Two things the model must not claim.**

- **It cannot claim a device is healthy.** Sections 2 and 4 together mean
  the absence of a fault report is not evidence of anything: the reporter
  may not have been listening, may be holding a stale cache, or may be
  reading a device that is gone. This is the same honesty caveat Run's
  `Running` already carries, and the Equipment page has to carry it in
  the same words rather than quietly implying the stronger claim.

  There is a third route to the same gap, found by the sibling spike
  rather than this one: hardware outlives a conductor that is killed, and
  no stop document is ever emitted. So neither the document path nor the
  alarm path notices a device still moving after the thing driving it
  died. Recorded here as well as in `spikes/conductor/` because it reads
  as an open question in each document separately and is one question.
- **It cannot answer "was this device faulted during that run."** Nothing
  in the engine retains that, so AROC could only ever record what a
  reporter happened to see. Recording a fault as a point event with an
  `occurred_at` is honest. Deriving an interval from two point events and
  querying against it is not, because a missed clear silently extends the
  interval forever.

**The configuration snapshot should stay deferred**, and section 6 is now
the reason rather than a suspicion. A snapshot is one
`read_configuration()` call away, which is exactly what makes it
dangerous: the easy implementation is the one that puts a badge number in
an append-only log.

**Where the boundary question lands.** Section 5 says a device's extent is
a client-side opinion, so AROC should register the prefix-identified
thing and not try to mirror an ophyd tree. A sibling spike at
`spikes/conductor/` is asking what happens when two writers share one
device; its unit of exclusion has to be the prefix for the same reason,
because that is the only name two independent clients agree on.

## What this spike did not do

No beamline, no real EPICS IOC, and no hardware. The camera's records are
hand-written rather than an areaDetector database, and the temperature
alarm is set by the IOC explicitly rather than computed by a record from
its HIHI and HHSV fields. That changes who decided the severity and not
what a client can see of it, which is what every claim above is about.

One rig detail worth knowing before editing `ioc.py`: every `pvproperty`
in a caproto PVGroup shares one `ChannelAlarm` unless given an
`alarm_group`, and a value write clears it. Without the `alarm_group` on
`Temperature_RBV`, the client's own put to the thermostat clears the
severity the group just set, and section 2 measures the rig instead of
EPICS. That is a caproto property and not an EPICS one.

Untested: `stage`/`unstage`, ophyd `Status` objects and their error paths,
areaDetector, anything about timing, and whether a real `bo` or `mbbi`
record behaves as the camera's records do here.

## When to delete this

When the model questions in section 7 are answered, which is the only
reason it exists. Keep `observations.json` if an equipment reporter is
ever written: it is what a client actually saw, and it makes a fixture
that needs neither EPICS nor a beamline.
