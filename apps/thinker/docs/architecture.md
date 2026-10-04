# Architecture

*The objects this package settles on, who is allowed to decide what, and the
one join that would pass every test while being wrong.*

[Thinking](thinking.md) says what a thinker reads and may conclude, in no code
at all. This page is the same thing with the names on it, for somebody about to
change one.

## The rule

**An adapter translates. The core decides.**

Four modules import the standard library and each other: `case`, `conclusions`,
`seams` and `think`. Everything facing outward is a Protocol in `seams` with an
implementation under `adapters/`, and an implementation's whole job is to turn
what its system speaks into this package's words and back. It does not pair,
judge, filter or interpret, because each of those is a decision and every
decision this package makes is made in one place a test can reach.

`tests/test_the_core_names_no_seam.py` holds that, and pins the membership:
four core modules, two outer ones, one adapter.

The rule cost something to keep. The reading seam used to hand back a finished
case, which read well and put the join inside the adapter. The join is by id,
and a join by position passes every test there is until somebody inserts a
step. Leaving it there would have meant trusting each future adapter to repeat
a rule rather than routing every one of them through it.

The conductor pairs its own two halves inside its adapter and is right to: it
builds both from one response, in one pass, with no second writer to drift
against. Here they are two responses from two routes, which is the case that
reasoning excludes.

## The pieces

```
   the core: four modules, the standard library, and each other
   ---------------------------------------------------------------------
   case.py                            seams.py
     Question    what was asked         Seeking      take
     Reading     the halves, unpaired   Claiming     claim
     Case        the halves, paired     Questioning  ask, read_back
     Step        one of them            Observing    read
     Outcome     every word the         Advising     propose, answer
                 record holds           Looking      three lookups a case
     Boundary    how much the record                 does not carry
                 was able to offer      Concluding   conclude
     assemble    the only way a
                 Case comes to be

   conclusions.py                     think.py
     Propose  Stop  Abstain  Refer      think()   one question, start to end
                                        Thought   what came back

   the adapter, and the two modules between
   ---------------------------------------------------------------------
   adapters/http_keeper.py    HttpKeeper, satisfying six of the seven
   config.py                  ThinkerConfig, and what builds an inference
   intake.py                  serve: take, claim, think, round again
```

`Reading` and `Case` are the pair worth understanding together. A reading is
what was read; a case is what it means once the halves are put against each
other. The seam produces the first and only `assemble` produces the second, so
there is exactly one way for a case to come into being.

**One adapter satisfies six seams and is passed once per seam a caller wants.** Which service
answers is a fact about a deployment; what a caller needs is a fact about the
caller. So `think` is handed exactly the three verbs it uses and cannot take a
question or claim one, and that is the argument list rather than a rule
anybody has to follow.

`Concluding` has no adapter here at all. There is no provider in this
repository, and a deployment's profile builds one.

## One thinking, in code

```
   intake.serve(seeking, claiming=, observing=, advising=, concluding=)
       Seeking.take(wait) ............... Question, or nothing
       Claiming.claim(inquiry_id) ....... True, or another thinker has it
           |
           v
   think(question, observing=, advising=, concluding=)
       |
   read     Observing.read(execution_id)
       |        -> Reading(asked=[(step_id, {...}), ...]   ordered, the
       |                   became={step_id: Outcome | None},  procedure's
       |                   execution_id, procedure, ended)    keyed, the
       |                                                      record's
       |        nothing is paired, and no objective went out
       |
   pair     assemble(reading, objective=...)
       |        join asked against became, on the id
       |        an outcome naming no step   -> MismatchedCaseError
       |        a step with no outcome      -> became=None, and it stays
       |        -> Case(steps, ended, objective)
       |               .unreached()        steps the record does not cover
       |               .ran_to_the_end()   whether every step was reported
       |               .boundary()         how much was visible
       |
   do       Concluding.conclude(case)
       |        -> Propose | Stop | Abstain | Refer
       |
   write    Advising.propose(...)    on Propose only, and first
       |    Advising.answer(inquiry_id, conclusion, boundary, proposal_id)
       v
   Thought(case, conclusion, proposal_id, inquiry_id)
```

**The writes are last, and there are two of them on one arm.** Nothing is
written until there is a conclusion, so a thinker that dies part way through
has advised nothing and answered nothing, and the question it held stays
claimed and unanswered rather than carrying a verdict nobody reached.

**The order within the arm is load bearing.** The proposal goes first and the
answer cites it, so a death between them leaves a proposal that reads as any
other actor's. The reverse would leave an inquiry naming a proposal nobody
made, which is a record pointing at nothing.

**Nothing narrows the ask.** A conductor asks for its own beamline because an
execution is dispatched to one. An inquiry names an execution and carries no
beamline, so a thinker takes whatever is open and a race between two of them is
settled by the claim.

**Anything raised in the loop is said, waited out, and tried again**, with no
judgement about which failures deserve it. A thinker running this way is a
daemon under a service manager that would restart it anyway, so exiting on a
refusal it judged permanent buys a crash loop in place of a retry loop, with
the log spread over process lifetimes instead of gathered in one. What is
caught changes who tries again, never what is written.

## The join, and what a join by position would do

```
        asked                      joined on              became
   ordered, the procedure's         the id           keyed, the record's
   -----------------------          ------           -------------------

   ("s1", {set motor:x 1.5})  <---- "s1" ---->  "Done"
   ("s2", {run operation-9})  <---- "s2" ---->  None      reported, no outcome
   ("s3", {set motor:x 2.0})  <---- "s3" ---->  absent    never reached at all

                                    "s9" ---->  "Done"    refused: the procedure
                                                          lists no such step, so
                                                          these are not both
                                                          about one execution
```

An execution's step carries two ids: its own, and the id of the composed step
it was dispatched from. Only the second is what the intent is keyed on, and
keying on the first would hand the core two halves that share no key at all and
read as two executions.

Position is not a shortcut to the same answer. It is the same answer until it
silently is not:

```
   today                            the day a step is inserted at the front

   asked[0] <-> became[0]  right    asked[0] = s0  <->  the outcome for s1  wrong
   asked[1] <-> became[1]  right    asked[1] = s1  <->  the outcome for s2  wrong
   asked[2] <-> became[2]  right    asked[2] = s2  <->  the outcome for s3  wrong

   green suite                      green suite, and every step mis-paired
```

That is what the reading seam hands back a `Reading` for. Both lists arrive in
the procedure's order today, so the wrong join passes every test there is, and
the only defence that survives a second adapter is having one place to make it.

## The naming this package settles on

**A seam is named for what this package does through it.** `Observing` reads
what an execution did, `Questioning` keeps the record of somebody asking,
`Advising` puts a run forward, `Concluding` turns a case into one of four
answers, `Seeking` finds a question nobody has taken up, `Claiming` takes one
up, and `Looking` goes back to the record for what a case does not carry. None
takes a `Port` suffix, since everything in that module is a seam and saying so
distinguishes nothing.

**A field is named for the act, not for the schema it came out of.** `asked`
and `became` rather than `procedure_step` and `outcome`. The pair reads as a
sentence about one step, and neither name survives being read as the other.

**A distinction worth drawing is a class, not a field.** Four conclusions are
four classes, because a field can be set wrong and a class cannot, and whatever
reads one keys off the class instead of parsing a word.

**`None` means the record is silent.** It is never a value the record could
have given and never a default standing in for one. A step whose `became` is
`None` was not reported on, which is a different fact from every outcome the
keeper has a word for. It is also the only structural fact in an outcome:
`unreached`, `boundary` and `ran_to_the_end` all test for it and none of them
reads a word, so what the keeper calls a step never decides a count.

**Two observers of one step stay two.** An `Outcome` carries what the driver
reported and what the engine said about the run the step opened, because the
keeper holds those as separate claims and declines to reconcile them. They
disagree in the case that matters most: a run step dispatched cleanly whose
engine then failed is reported done, and anything keeping the first word alone
would show a thinker a failure wearing the word for success. Choosing between
them is not this package's to do, so both travel and whatever thinks is the
first thing given the chance to weigh them.

## What is deliberately not an object

**A structure for the objective.** It is free text on the case and free text on
the record, and this package validates neither: what somebody wants to know is
not a shape this has any business enforcing. It arrives from the record in one
mode and from the command line in the other, and `Question` is what makes those
two the same thing by the time anything thinks.

**A thinker.** `think` is a function over three seams, and the loop around it
is a function over five. A class would hold the seams as state, and nothing
needs that state to outlive a call.

**A reason on a proposal.** The record deliberately carries none, and smuggling
one into a proposal's parameters would write unbounded free text into a row
nothing can edit afterwards.

**A confidence.** The one refusal this project will not trade away. A number a
thinker assigns its own conclusion reads as measurement and is assertion.

`Boundary` is the nearest thing to a number that travels, and it is the
opposite kind. It counts what was visible rather than rating what was
concluded, and it is derived from the case the inference was shown rather than
reported by whatever formed the conclusion, so nothing can inflate it.

## Where the vocabulary is the keeper's, and why that is not a leak

`Propose` carries an operation id, and a case is keyed by ids the keeper
minted. That is deliberate. A proposal is refused unless its parameters satisfy
the schema its operation declares, so an id this package renamed would be an id
it had to translate back before anything could act on it, and the translation
would be the only thing the new name bought.

What would be a leak is a wire format, a route, a status code or a header
reaching the core. None does, and `tests/test_the_core_names_no_seam.py` is
what keeps it that way.
