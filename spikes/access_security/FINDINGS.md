# Access security findings

Measured against EPICS base 7.0.10.0 and pyepics, with a real `softIoc`
serving Channel Access on port 5084 and an access configuration file that
`ascheck` validated first. Numbers below are from `findings.json`, which
`probe.py` wrote.

The headline is that this layer does what the other four candidates could
not, and fails at something none of them was asked about. It refuses a
write from a client that never opted in, per record, in under a
millisecond, and it cannot tell two processes on one workstation apart.

## 1. The gate decides the write, and the client knows in 0.7 ms

A rule gated on a PV through `INPA` and `CALC` flips write permission
while the IOC runs.

```
   write while unclaimed          allowed, 0.0 -> 1.0
   write while claimed by other   refused, 1.0 unchanged
   write after release            allowed, 1.0 -> 3.0

   access-rights event after the claim     0.0007 s, write_access False
   access-rights event after the release   0.0007 s, write_access True
```

The timing is the part that decides something. Both figures are measured
from before the put on the gate record, so 0.7 ms covers asking and being
told, and a conductor that claims a device and writes to it on the next
line is not racing anything. A claim can bracket a step.

That is loopback. A real beamline puts a network between the two and the
figure will grow, but three orders of magnitude of headroom is a
different situation from the one where this would have to be designed
around.

## 2. pyepics raises, on all three ways of writing

Every route a caller might take reports the refusal the same way:

```
   pv.write_access, before trying anything   False
   pv.put(value, wait=True)    CASeverityException:  put returned 'Write access denied'
   pv.put(value, wait=False)   CASeverityException:  put returned 'Write access denied'
   epics.caput(name, value)    CASeverityException:  put returned 'Write access denied'
   the value afterwards        unchanged, all three times
```

Two things follow for `epics_control`. A refusal is an exception with a
distinguishable type, so `Refused` and `Broke` can be told apart at the
seam rather than by parsing text. And `pv.write_access` answers before
the attempt, for free, so an adapter can decline to write at all rather
than write and catch, which is the same shape `_refuse_if_held` already
has for the in-process ledger.

Note that `wait=False` raises too. The refusal comes back from the server
on the put itself, not from a later completion callback.

## 3. One claim, one record, and reads never stop

```
   the claimed record        refused,  write_access False
   the record beside it      allowed,  0.0 -> 6.0
   a record in DEFAULT       allowed,  0.0 -> 7.0
   reads of the claimed one  read_access True, value readable throughout
```

This is the property the whole layer was worth measuring for. Queueserver
locks the queue or the environment and never a device; here a claim on
one motor says nothing about the motor beside it, and a monitor watching
the claimed record keeps working. A claim stops writers without blinding
anybody.

The cost is in the configuration rather than the mechanism. Permission
attaches to an access security group, not to a record, so per-record
gating needs one group per record and every group enumerated in the file.
For a beamline that is a generated `.acf`, and nothing here measured what
several hundred groups cost the IOC at load or on reload.

## 4. Two processes on one workstation are the same client

This is the negative result, and it is the one that shapes a design.

`m2`'s holder is the user running the probe, so this is the case where
the claim is ours and a rival should be shut out.

```
   the holder writes                      allowed, 8.0
   another process, same user, same host  allowed, 9.0
   username the IOC saw                   dgursoy
```

Access security matches on who and where: the CA client's userid and its
hostname. Two Python processes on one workstation are identical on both,
so the group cannot see a difference between the conductor and the rival
that `spikes/conductor/` drove into a running scan. Against that
particular rival, this mechanism is no better than the in-process ledger.

What it means is a deployment requirement rather than a defect. **The
conductor has to run as its own OS account for a holder rule to mean
anything.** That is the same question queueserver's findings left open
about user groups, arriving here as a hard constraint rather than an
option, and it is cheap: a service account and a `UAG` with one name in
it.

It also means the two layers do different jobs and both are needed. A
claim service keyed on record names can tell two processes apart, because
it hands out identities itself. Access security cannot, but it binds the
clients a claim service will never reach. Neither one is a superset of
the other.

## 5. TRAPWRITE is a flag with nothing behind it

Both gated rules carry `TRAPWRITE`. After a trapped write:

```
   the IOC's own output grew by   0 bytes
```

The flag marks writes for a listener that stock base does not start.
Getting an audit trail means installing something that registers one,
`caPutLog` being the usual choice, which is a second component to deploy
and was not tested here. So the write log that would say who collided is
available in principle and is not free.

## What this recommends

**This is the enforcement floor, and it works.** Sections 1 through 3
answer the three questions that mattered: the gate decides, a refusal is
legible to the adapter already in the tree, and the granularity is the
record rather than the instrument. Nothing else surveyed does all three.

**Budget for the conductor to have its own account.** Section 4 turns
what looked like a configuration detail into a precondition. A holder
rule written without it is a rule that refuses everybody or nobody.

**The gate PV needs an owner, and this spike deliberately gave it none.**
Both claim records sit in `DEFAULT`, so anything can set them, which
means the gate is exactly as strong as whatever holds it. Putting the
gate records themselves in a group writable only by the claim service's
account closes that, and it is the same mechanism one turn down.

**Two layers, not one.** A claim service keyed on record names for
cross-client coordination among things that opted in, and access security
underneath for everything that did not. Section 4 is why neither replaces
the other.

## What this spike did not do

It used `ao` records rather than motor records, so nothing here says what
a refused write does to a motor mid-travel. A `.STOP` that cannot be
written is a different situation from a `.VAL` that cannot, and safety
records that must always be writable are a category this spike has no
opinion about.

It ran two groups. Nothing here says what several hundred cost at load,
what a reload costs a running IOC, or whether a generated `.acf` stays
legible at that size.

It did not reload access security while the IOC was running.
`asSetFilename` plus a subroutine record is the documented path and was
not exercised, so the claim that rules can be changed without a restart
is the manual's rather than this spike's.

It did not test `caPutLog`, so section 5 says only that the flag alone
produces nothing.

It ran on loopback, as one user, on macOS. Hostname matching, the
`HAG` half of the mechanism, was never exercised against a second host.
