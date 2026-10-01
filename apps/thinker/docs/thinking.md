# Thinking

*What a thinker reads, what it is allowed to conclude, and what it refuses to
claim about its own answer.*

## The job

A thinker reads what a job was asked to do and what became of it, puts the two
side by side, hands the whole picture to whatever does the thinking, and writes
the answer down. Three moves in a fixed order, once per question.

```
   read       the record    -->  what the job was asked to do
                            -->  what became of it

   conclude   the whole case  -->  whatever does the thinking,
                                   which the deployment supplies

   record     the answer     -->  the record
                                  (and a proposal first, on one of the four)
```

There is no provider here. No prompt, no model name, and no adapter onto one.
What this settles is the shape of the question and the shape of the answer:
what a reader is given to think about, and which answers it is allowed to give.
Everything behind that is built by whoever deploys it.

Every call goes out and none comes in. A thinker needs no inbound port, and
nothing can hand it work.

## One thinking, end to end

```
   find a question        ask the record for one nobody has taken up, and
                          hold the request open until there is one

   claim it               say this thinker is answering it

   read both halves       what the procedure asked for, from one route, and
                          what the record says became of it, from another

   pair them              step by step, joined on the id the record names
                          for the purpose, and never on position

   conclude               the whole case goes out, and one of four words
                          comes back

   write                  a proposal first, when that is the answer, and
                          then the answer itself citing it
```

**Going looking is not polling.** The request is held open until a question
appears, so a waiting thinker is one connection rather than a question asked
every few seconds, and a question put anywhere reaches it in milliseconds. The
query is still what answers it, so a lost wake-up costs a second of latency and
never a question nobody picks up. The direction of every call is unchanged: a
held request is one this side opened.

### Both halves travel, or the question is not worth asking

The record alone says a step ended refused and cannot say what the step was
for, so a reader can tell that something did not happen and not what. The
intent alone is the procedure, which is the same for every execution of it and
therefore says nothing about this one. Paired, they look like this:

```
   what the procedure asked for      what the record says became of it
   --------------------------------------------------------------------
   s1   move the sample to 0.5       Done
   s2   run a tomography scan        Done, and the engine said it failed
   s3   move the sample to 1.0       Refused
   s4   run a tomography scan        nothing was ever said
```

Three of those four rows are the interesting ones, and each is a different
thing.

**A step carries more than one word about how it ended.** What the driver
observed and what the engine said about the run that step opened are two
separate claims, and the record refuses to reconcile them. They agree most of
the time, and the case where they do not is the one a reader most needs: a run
dispatched cleanly whose engine then failed is reported done, so a thinker
shown only the driver's word reads a run that broke as a run that worked. A
third word travels with them, the class of whatever was raised.

**Unreported is not skipped.** Skipped means the walk reached the step and
passed it over. Nothing at all means nobody ever said, which is what a driver
that died leaves behind. They stay distinct the whole way through, because
collapsing them would throw away the difference between a walk that decided
against a step and a walk that never got there.

For the same reason, whether an execution ended is read off its status and
never counted from its outcomes. An execution can have an outcome for every
step and not be ended, and an ended execution can be missing most of them.

**The join is by id.** Joining by position would look like it worked, because
both lists come back in the procedure's order today. It would be a guess that
happened to hold, and the day a step is inserted it would pair every later step
with the wrong outcome and say nothing about it. An outcome naming a step the
procedure does not list is refused outright rather than dropped, and the
refusal names every such step rather than the first.

### Four conclusions, and the one that writes twice

```
   Propose    run this next
   Stop       the objective is met, and running more would be waste
   Abstain    nothing here warrants a next run that this can see
   Refer      a person should look at this
```

Four classes rather than one field carrying a verdict, because a field can be
set wrong and a class cannot.

Stop and Abstain are the pair most easily collapsed and the pair it costs most
to collapse. Stop is a finding about the objective: it is met. Abstain is a
finding about the thinker: it sees no next step. A facility told the second
when the first was true keeps running, and one told the first when the second
was true stops early.

All four are written onto the inquiry that asked. Only Propose writes anywhere
else, and the order within it is load bearing:

```
   the proposal first    a thinker that dies between the two leaves a
                         proposal that reads as any other actor's

   the answer second     the reverse would leave an inquiry naming a
                         proposal nobody made
```

## What it promises

**That a conclusion was reached from a case that was read.** Not that the
conclusion is right. That is the whole of what this guarantees, and the rest of
this section is about making it checkable.

**That it says how much it saw.** An answer carries how many of the execution's
steps the record covered when it read, and whether the execution had ended. The
same conclusion drawn from two reported steps of six is a weaker claim than one
drawn from six of six, and once the execution moves on nothing downstream can
tell them apart. This says how much was visible and never whether the
conclusion was good.

**That all four answers are written.** A thinker that looked and found nothing
is distinguishable on the record from one that never ran, which is not a
distinction a printed line on somebody's terminal could hold once nobody is
standing there.

**That nothing is written until there is a conclusion.** A thinker that dies
part way through has advised nothing and answered nothing, so the question it
held stays claimed and unanswered rather than carrying a verdict nobody
reached.

**That a proposal the record would refuse comes back as an error.** A proposal
is refused unless its parameters satisfy the schema the operation declares, and
that refusal is let through rather than swallowed, because a conclusion that
could not have run is worth more as an error than as a row.

## What it refuses to claim

**That an answer is any good.** There is no confidence score and no
self-rating, and there will not be one. A thinker rating its own answer
produces the artefact this system refuses everywhere else, where a thing
reporting on itself was taken for a finding about the thing. A number a thinker
gives itself reads as a measurement and is an assertion.

**That it can steer.** Every call goes out and none comes in. Nothing in the
record touches a running execution and a conductor's verbs are all outbound, so
a conclusion reached while an execution is still walking has nowhere to arrive.
Advice goes on the record and whatever reads next finds it there. Steering
would be a change to what the record and the conductor are, not a seam missing
here.

**That a failure is an abstention.** Nothing is caught. A record that cannot be
reached and a provider that raised both stop the thinking, and neither becomes
an answer. Returning Abstain on a failure would read as a thinker that looked
and found nothing, and would be a thinker that did not look.

**That it knows why anything failed.** The record holds the class of what was
raised and never a sentence about it, on purpose. So a case says what kind of
thing went wrong and never why, and a thinker that needs the why needs to read
something other than the record.

**That a proposal says what thought produced it.** The reason a thinker gives
travels back to whoever called it and does not go onto the proposal. Smuggling
one into the parameters would be writing unbounded free text into a record
nothing can edit afterwards, and a field that reads as an explanation and is a
generated sentence is worse than no field.

## Where it stops

A thinker reads and concludes. Four things on the other side of that line
belong to somebody else:

```
   the thinking itself            whatever the deployment supplies
   running the work               a conductor, at the beamline
   turning advice into work       a separate act, against permission
                                  somebody granted in advance
   whether the advice was good    whoever reads the record afterwards
```

The third is the one worth saying plainly. An answer goes on the record as a
suggestion, and a facility that runs whatever is suggested has turned advice
into an order, outside anything this project controls.

[Running one](running.md) covers the ways to arrive at a question and what each
exit status means. [Architecture](architecture.md) draws one thinking object by
object, and says who is allowed to decide what. [Contract](client-contract.md)
covers what this relies on at its edge. [Glossary](glossary.md) pins each word,
including the two this project deliberately does not use.
