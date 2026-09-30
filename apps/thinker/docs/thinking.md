# Thinking

*What one thinking promises, what it reads, and what it is allowed to conclude.*

A thinking is three moves in a fixed order, once per question. Then the process
either exits or goes looking for the next question, depending on how it was
started.

| | |
| --- | --- |
| read | ask the keeper what the execution was asked to do and what became of it, and pair the halves into a case |
| conclude | hand the whole case to whatever does the thinking |
| record | write the conclusion onto the inquiry that asked, and the proposal first if there is one |

`think` is the function, `Thought` is what comes back, and `python -m thinker` is
the process that runs it. Everything above the two seams is four modules that
import the standard library and each other, which is what makes changing provider
an adapter rather than a rewrite.

## What the service promises, and what it cannot

**It promises that a conclusion was reached from a case that was read.** Not that
the conclusion is right. Nothing here scores a conclusion, and nothing here could:
a thinker rating its own answer produces the same artefact the conductor refuses at
its engine seam, where the engine's own word for how a run went was taken for a
finding about the run. A number a thinker assigns itself reads as measurement and
is assertion.

**It cannot steer.** Every call goes out and none comes in. No command in the
keeper touches a running execution and the conductor's verbs are all outbound, so a
conclusion reached while an execution is still walking has nowhere to arrive.
Steering is a change to what the keeper and the conductor are, not a seam missing
here.

**It cannot be reached, and it no longer has to be.** Nothing dispatches work to a
thinker, because nothing in this tree reacts to an event by writing another one.
What changed is that a thinker now goes looking instead of waiting to be told: it
asks the keeper for a question nobody has taken up, claims it, and answers it.

**Going looking is not polling, and the difference is the keeper's to provide.**
The request is held open until a question appears, so a waiting thinker is one
connection rather than a question asked every few seconds, and a question put
anywhere reaches it in milliseconds. A trigger on the record wakes the held
request; the query is still what answers it, so a lost wake-up costs a second of
latency and never a question nobody picks up.

That leaves the direction of every call unchanged, which is the part worth being
careful about. A held request is one this side opened. Nothing listens here, and
a thinker still needs no inbound port.

**Every conclusion is now written, and that is new.** `Propose` used to be the
only one the keeper had a place for, so a `Stop`, an `Abstain` and a `Refer`
existed only in what the command line printed. All four now land on the inquiry
they answer, which is what makes a thinker that looked and found nothing
distinguishable from one that never ran.

**It says how much it saw, and that is not a score.** An answer carries how
many of the execution's steps the record covered when it read, and whether the
execution had ended. The same conclusion drawn from two reported steps of six
is a weaker claim than one drawn from six of six, and once the execution moves
on nothing downstream can tell them apart. Those two counts say how much was
visible and never whether the conclusion was good, which is the line this
package will not cross.

## Both halves of the case travel

A case carries what the procedure asked for and what the record says became of it,
paired step by step. Either half alone is a worse question to ask.

The record alone says that a step ended `Refused` and cannot say what the step was
for, so a reader of it can tell that something did not happen and not what. The
intent alone is the procedure, which is the same for every execution of it and
therefore says nothing about this one.

What the record half says about one step is more than one word. The keeper holds
two claims about how a step ended and refuses to reconcile them: what the driver
observed, and what the engine said about the run that step opened. Both reach the
case. They agree most of the time and the case they do not is the one a reader
most needs: a run step dispatched cleanly whose engine then failed is reported
`Done`, so a thinker shown only the driver's word reads a run that broke as a run
that worked. A third word travels with them, the class of whatever was raised,
and it is the most the record will ever hold about a failure. The keeper refuses
free failure text on purpose, so a case says what kind of thing went wrong and
never why, and a thinker that needs the why needs a seam onto something other
than the record.

The pairing is also what makes the thinking checkable by the person who asked for
it. A conclusion is only as good as the case behind it, and the commonest way for
one to be wrong is for the case to be thinner than the reader assumed. An execution
whose record covers two of its six steps supports very little, and the only way to
notice is to see it, which is why `Thought` carries the case back beside the
conclusion and the command line prints how much of it was covered.

## The join is by id, and the keeper names the key

An execution's steps and a procedure's steps are two lists, and they are paired on
`procedure_step_id` matching `step_id`, which is what the keeper's own route says
the field is for.

Joining by position would look like it worked. Both lists come back in the
procedure's order today, so a positional join would agree with an id join on every
execution now in the system. It would be a guess that happened to hold, and the day
a step is inserted it would pair every later step with the wrong outcome and say
nothing about it.

The pairing happens in the core and not in the adapter that read the halves. A
seam that handed back a finished case would put this rule inside each
implementation of it, and a rule that can be got wrong silently belongs where
everything goes through it. The reading seam returns the halves as it found them
and `assemble` is the only way a case comes into being.

An outcome reported against a step the procedure does not list is refused rather
than dropped, because the two halves are then not about one execution and no
pairing of them is worth making. `MismatchedCaseError` names every such step, not
the first one.

## Unreported is not skipped

A step with no outcome in the record and a step the keeper marked `Skipped` stay
distinct all the way through. The keeper draws that line and collapsing it here
would throw away the difference between a walk that decided not to run a step and a
walk that stopped before reaching it.

For the same reason, whether an execution ended is read off its status and never
counted from its outcomes. `Ended` is the keeper's word about the execution;
counting outcomes would be this project inferring one, and the two answer different
questions. An execution can have an outcome for every step and not be `Ended`, and
an `Ended` execution can be missing most of them.

## Four conclusions, and the one that writes twice

| | |
| --- | --- |
| `Propose` | run this next |
| `Stop` | the objective is met, and running more would be waste |
| `Abstain` | nothing here warrants a next run that this can see |
| `Refer` | a person should look at this |

Four distinct classes rather than one record carrying a verdict string. A field can
be set wrong and a class cannot, and whatever reads a conclusion keys off the class
rather than parsing a word. It is the move the keeper and the conductor both make.

`Stop` and `Abstain` are the pair most easily collapsed and the pair it costs most
to collapse. `Stop` is a finding about the objective: it is met. `Abstain` is a
finding about the thinker: it sees no next step. A facility told the second when the
first was true keeps running, and one told the first when the second was true stops
early.

All four are written onto the inquiry that asked. `Propose` writes twice: it
becomes a proposal through the keeper's own API first, under the thinker's own
credential, and the answer then cites it. The keeper refuses a proposal unless the
parameters satisfy the schema the operation declares, and that refusal is let
through rather than swallowed, because a conclusion that could not have run is
worth more as an error than as a row.

The order is load bearing. A thinker that dies between the two leaves a proposal
that reads as any other actor's, which is harmless; the reverse would leave an
inquiry naming a proposal nobody made.

The other three used to go no further than what the command line printed, which
held only while somebody was standing there reading it. Nobody is, once a thinker
finds its own work, and that is the change that made the record the only copy.

## Why a proposal carries no reason

`said` is free text on every conclusion and it does not travel with a proposal. The
proposal record carries an operation and parameters and deliberately no reason, and a
thinker that smuggled one into `parameters` would be writing unbounded free text
into a record nothing can edit afterwards.

The reason reaches the caller instead, which is the same place the three unstorable
conclusions go. What it costs is that a proposal in the keeper does not say what
thought produced it. That is the honest state of the record rather than a gap this
project may close on its own: the field would have to exist in the keeper first, and
a record that reads as an explanation and is a generated sentence is worse than no
field.

## Why a failure is never a conclusion

Nothing is caught. A keeper that cannot be reached and a provider that raised both
stop the thinking, and neither becomes an answer.

Returning `Abstain` on a failure would read as a thinker that looked and found
nothing, and would be a thinker that did not look. It is the same call the conductor
makes in the other direction and for the same reason: it refuses to report `Broken`
for a step no seam ran, because unsticking a queue is not worth a false line in a
permanent record.

The exit status says whether the thinker ran and never what it concluded. Any of the
four is a success, a keeper or provider failure is not, and a configuration that
cannot be used is its own status because it is the one a person can fix without
looking at the beamline.

A thinker that finds its own work reports almost nothing through a status, because
it does not end when something goes wrong. A failure there is said out loud, waited
out and tried again, and the record still hears nothing about the thinking that did
not happen. What is caught changes who tries again, never what is written.

## What is not decided yet

**No provider adapter ships here.** There is one adapter, over the keeper's own API,
and `Concluding` is satisfied by whatever a deployment's profile builds. The check
that no adapter imports a sibling adapter therefore ranges over a single file today
and can find nothing, which is accurate rather than pointless: it is the rule that
starts mattering on the day the second adapter lands, and a rule written afterwards
is a rule written after the import it would have caught.

**A second reading seam.** There is no stream a thinker can reach that the keeper is
not already the record of. When there is one, it earns a Protocol; until then a
second one would be a single interface with a single implementation reading the same
API as the first.
