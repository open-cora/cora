# What a claim can protect, and where it stops

*A procedure that moves a file and reconstructs it needed scopes, and
there was no honest answer to what they should be. Three measurements
say why: the claim vocabulary is about beamline hardware held during a
walk, and work that outlives the walk is outside it. This page records
what was measured, what it means for a rule enforced in three projects,
and what to do instead.*

## The question that started it

A step must declare at least one scope. The rule is in three places and
all three give one reason:

> a step that declared nothing would be one this system believes touches
> no hardware

For a tomography scan that is exactly right, and the hazard behind it is
real: two writers on one motor produce data that is wrong, sometimes
self-consistently wrong, and nothing raises.

For a transfer it is not right. A transfer touches no hardware. Asked
what it should declare, there is no truthful answer, and every candidate
is a fiction the record would carry forever, because a procedure cannot
be retired.

## Three reasons the ledger cannot guard this work

**A scope is fixed in the procedure and the dataset is a parameter.** The
thing two reconstructions contend for is one output directory, named
after the file each was given. A procedure's scopes are written before
any dispatch, so a step cannot claim the dataset it will be handed. It
can only claim the whole results area, which would serialise every
reconstruction at the beamline. The facility runs thirty-six at once.

**The ledger is per process and in memory.**
`apps/conductor/src/conductor/claims.py` says so plainly: two conductors
hold two ledgers and neither can see the other's, and one conductor to a
beamline is a deployment topology that nothing enforces. So a claim
already arbitrates less than it appears to, even for hardware.

**A handoff releases the claim while the work goes on.** This is the
decisive one and it is structural.
`apps/conductor/src/conductor/conduct.py` runs a step inside
`with book.granted(holder, step.claim)` and `WorkHandedOffError` is
raised inside that block, so the context manager exits and the claim is
released at the moment of handoff. The transfer then runs for minutes
and the reconstruction for hours, with nothing held.

A perfect per-dataset scope would still be released before the work it
named had started in earnest. No spelling of a scope fixes that, because
a claim is scoped to a walk by construction and this work is defined by
outliving one.

## What that means for the rule

The rule conflates two cases that look identical in a request and are
opposite in meaning. A step with no scopes is either somebody who forgot
to say what it drives, which is the hazard, or something that genuinely
drives nothing here, which is the truth about every step whose work
happens at another facility.

Refusing both is what the three projects do today. It was correct while
every step drove a motor, and the first procedure that moves a file is
the one that shows it was a rule about scans rather than about steps.

## What to do instead

**Let a step say it drives nothing here, and keep refusing silence.** The
distinction worth preserving is between an omission and a declaration,
not between one scope and none. A step that declares no devices and says
so explicitly is making a checkable claim about itself; a step that
simply left the list out is not.

That is a change in three places, because all three enforce the rule and
each ships as its own repository:
`beamlines/descriptor.py`,
`apps/keeper/src/keeper/execution/features/define_procedure/route.py`,
and `apps/conductor/src/conductor/procedure.py`.

**Do not put paths in scopes.** `Scope.record` drops everything after a
dot, because for a motor `m1.VAL` and `m1.STOP` are one device. On a
filename that silently rewrites what was asked for: a claim on
`/eagle/.../a.h5` becomes a claim on `/eagle/.../a`. Measured, and the
result is conservative rather than dangerous, which is worse in its way
because nothing complains.

**Protect the output somewhere that outlives a walk, or not at all.** Two
reconstructions of one dataset collide because the output path is
derived from the input name and the defaults clear the folder. That is
real and the ledger cannot see it. Either the record refuses to dispatch
work naming a dataset another live execution already named, which is a
question for the keeper rather than for a claim, or the collision is
accepted and visible, because both executions are in the record.

## What this does not say

That claims were a mistake. They do the job they were built for, which
is a walk holding a motor while it turns, and
`apps/conductor/src/conductor/claims.py` is clear that the hazard was
measured rather than assumed. What is new is work that finishes
somewhere else, which the vocabulary was never asked about.
