# Architecture

*The objects this package settles on, and who is allowed to decide what.*

Six objects and one rule. The rule is the load-bearing half: the objects are
easy to rename and the rule is what stops the package drifting back into
being a keeper client with a domain veneer on it.

## The rule

**An adapter translates. The core decides.**

Everything facing outward is a Protocol in `seams.py` with an implementation
under `adapters/`. An implementation's whole job is to turn what its system
speaks into this package's words, and back again. It does not pair, judge,
filter or interpret, because each of those is a decision and every decision
this package makes is made in one place where a test can reach it.

The rule cost something to keep. The reading seam used to hand back a
finished case, which read well and put the join inside the adapter. The join
is by id, and a join by position passes every test there is until somebody
inserts a step. Leaving it there would have meant trusting each future
adapter to repeat a rule rather than routing every one of them through it.

The conductor pairs its own two halves inside its adapter and is right to:
it says both are built from one response, in one pass, with no second writer
to drift against. Here they are two responses from two routes, which is the
case that reasoning excludes.

## The objects

| Object | Where | What it is | What it is not |
| --- | --- | --- | --- |
| `Question` | `case.py` | what was asked: which inquiry, which execution, and toward what | anything about the answer |
| `Reading` | `case.py` | the two halves as a record hands them over, keyed and unpaired | a case, and not anything to judge |
| `Boundary` | `case.py` | how much of the execution was in front of the thinker | a score, and never a confidence |
| `Case` | `case.py` | one execution, every intent paired with what became of it, plus the objective | a claim that any of it succeeded |
| `Step` | `case.py` | one thing meant to happen, and what became of it | a keeper procedure step, reshaped |
| `Outcome` | `case.py` | how a step ended, in each of the words the record holds about it | a judgement on whether it went well |
| `Conclusion` | `conclusions.py` | one of four judgements, as four classes | a verdict string, and never a score |
| `Thought` | `think.py` | one thinking end to end: read, concluded, written | a record of anything |
| `ThinkerConfig` | `config.py` | where the keeper is, who this is when it gets there, what builds an inference | a place for model settings |

`Reading` and `Case` are the pair worth understanding together. A reading is
what was read; a case is what it means once the halves are put against each
other. The seam produces the first and only `assemble` produces the second,
so there is exactly one way for a case to come into being.

## One thinking, object by object

Nothing below is a server, and the loop is deliberately drawn out of it. What
follows is one thinking, from a question named on a command line to the exit
status. A thinker that finds its own work runs the same path with two moves in
front of it, which the section after this one draws.

```
  argv                              thinker.toml
  --config thinker.toml             [keeper]    base_url, token
  --inquiry inq-1                   [inference] profile
    or --execution exec-1
       --objective "find the edge"
         \                                /
          v                              v
        __main__.main()
            |
            |  load(path) .......................... ThinkerConfig
            |  concluding_for(config) .............. Concluding     (else exit 2)
            |  HttpKeeper(http, base_url, token) ... Observing,
            |                                       Questioning,
            |                                       Advising
            |
            |  asked(keeper, arguments) ............ Question
            |      --inquiry     claim it, and stop at exit 3 if refused
            |                    POST /inquiries/inq-1/claim
            |                    GET  /inquiries/inq-1
            |      --execution   open one, and claim nothing
            |                    POST /inquiries
            |
            v
        think(question, observing=, advising=, concluding=)
            |
   read     |  keeper.read("exec-1")
            |      GET /executions/exec-1           the record
            |      GET /procedures/proc-1           the intent
            |      |
            |      v
            |  Reading(
            |      asked  = [("s1", {...}), ("s2", {...})]  ordered, a procedure is
            |      became = {"s1": Outcome("Done", None, None),  keyed, the record
            |                "s2": None}                        cites the step
            |      execution_id, procedure, ended
            |  )
            |  nothing has been paired, and no objective went out
            |
   pair     |  assemble(reading, objective="find the edge")
            |      join asked against became, on the id
            |      an outcome naming no step  ->  MismatchedCaseError
            |      a step with no outcome     ->  became=None, and it stays
            |      |
            |      v
            |  Case(
            |      steps = (Step(index, step_id, asked, became), ...)
            |      ended, objective                 the objective arrives here
            |  )
            |      .unreached()       the steps the record does not cover
            |      .ran_to_the_end()  whether every step was reported on
            |
   conclude |  inference.conclude(case)
            |      ->  Propose | Stop | Abstain | Refer
            |
   record   |  if Propose:  keeper.propose(operation_id, parameters)
            |                   POST /proposals  ->  proposal_id
            |
            |  keeper.answer(inquiry_id, conclusion, case.boundary(), proposal_id)
            |      POST /inquiries/inq-1/answer
            |      all four conclusions, and the proposal only on one
            v
        Thought(case, conclusion, proposal_id, inquiry_id)
            |
            v
        stdout, as JSON, exit 0
```

The writes are last and there are two of them on one arm. Nothing is written
until there is a conclusion, so a thinker that dies part way through has
advised nothing and answered nothing, and the inquiry it held stays claimed
and unanswered rather than carrying a verdict nobody reached.

The order within the arm is load bearing. The proposal goes first and the
answer cites it, so a death between them leaves a proposal that reads as any
other actor's. The reverse would leave an inquiry naming a proposal nobody
made, which is a record pointing at nothing.

The case travels back beside the conclusion for a related reason. A conclusion
is only as good as the case behind it, and the commonest way for one to be
wrong is for the case to be thinner than its reader assumed.

Only a configuration that will not load is caught on that path. A keeper that
cannot be reached ends the run with a status of 1, and a provider that raised
ends it with a traceback. Neither becomes `Abstain`. The status says whether
the thinker ran and never what it concluded, so all four conclusions are 0.

## The loop, and the two moves it puts in front of that

`--serve` replaces argv as the source of the question. Everything from `think`
down is the diagram above, unchanged.

```
  intake.serve(seeking, questioning=, observing=, advising=, concluding=)
      |
      |  take(wait) ......................... Question or nothing
      |      GET /inquiries?status=Open&limit=1&wait=30
      |      held open by the keeper until a question is there
      |      nothing back means the wait ran out, so ask again
      |
      |  claim(inquiry_id) ................... True or False
      |      POST /inquiries/inq-1/claim
      |      False means another thinker has it, so ask again
      |
      v
  think(question, observing=, advising=, concluding=)
      |
      v
  a line on stderr, and round again
```

**The loop holds five seams and hands a thinking three.** It can take and
claim; `think` cannot, and that is the argument list rather than a rule
anybody has to follow. A thinking cannot answer a question nobody gave it.

**Nothing narrows the ask.** A conductor asks for its own beamline because an
execution is dispatched to one. An inquiry names an execution and carries no
beamline, so a thinker takes whatever is open and a race between two of them
is settled by the claim.

**Anything raised is said, waited out, and tried again**, with no judgement
about which failures deserve it. A thinker running this way is a daemon under
a service manager that would restart it anyway, so exiting on a refusal it
judged permanent buys a crash loop in place of a retry loop, with the log
spread over process lifetimes instead of gathered in one.

**What is caught changes who tries again, never what is written.** A provider
that raised is retried and never recorded, so the question stays unanswered
rather than carrying an `Abstain` nothing found. That is the same refusal the
one-shot path makes; only the thing that tries again is different.

## The join, and what a join by position would do

The pairing `assemble` performs, on the key the keeper names on both sides:

```
        asked                      joined on              became
   ordered, the procedure's         the id           keyed, the record's
   -----------------------          ------           -------------------

   ("s1", {set motor:x 1.5})  <---- "s1" ---->  "Done"
   ("s2", {run operation-9})  <---- "s2" ---->  None       reported, no outcome
   ("s3", {set motor:x 2.0})  <---- "s3" ---->  absent     never reached at all

                                    "s9" ---->  "Done"      refused: the procedure
                                                            lists no such step, so
                                                            these are not both
                                                            about one execution
```

An execution's step carries two ids: its own, and the `procedure_step_id` of
the composed step it was dispatched from. Only the second is what the intent is
keyed on, and keying on the first would hand the core two halves that share no
key at all and read as two executions.

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

**A seam is named for what this package does through it.** `Observing`
reads what an execution did, `Questioning` keeps the record of somebody
asking, `Advising` puts a conclusion and a run forward, and `Concluding`
turns a case into one of four answers. None takes a `Port` suffix, since
everything in that module is a seam and saying so distinguishes nothing.

The three that reach the keeper are three Protocols rather than one, even
though one adapter satisfies all three and the entrypoint passes it three
times. Which service answers is a fact about a deployment; what a caller
needs is a fact about the caller, and `think` is now handed exactly the
verbs it uses and cannot open a question or claim one.

**A field is named for the act, not for the schema it came out of.** `asked`
and `became` rather than `procedure_step` and `outcome`. The pair reads as a
sentence about one step, and neither name survives being read as the other.

**A distinction worth drawing is a class, not a field.** Four conclusions are
four classes, because a field can be set wrong and a class cannot, and
whatever reads one keys off the class instead of parsing a word.

**`None` means the record is silent.** It is never a value the record could
have given and never a default standing in for one. A step whose `became` is
`None` was not reported on, which is a different fact from every outcome the
keeper has a word for. It is also the only structural fact in an outcome:
`unreached`, `boundary` and `ran_to_the_end` all test for it and none of
them reads a word, so what the keeper calls a step never decides a count.

**Two observers of one step stay two.** An `Outcome` carries what the driver
reported and what the engine said about the run the step opened, because the
keeper holds those as separate claims and declines to reconcile them. They
disagree in the case that matters most: a run step dispatched cleanly whose
engine then failed is reported `Done`, and anything keeping the first word
alone would show a thinker a failure wearing the word for success. Choosing
between them is not this package's to do, so both travel and whatever thinks
is the first thing given the chance to weigh them.

## What is deliberately not an object

**A structure for the objective.** It is free text on the case and free text
on the record, and this package validates neither: what somebody wants to know
is not a shape this has any business enforcing. It stopped being only the
caller's the day the keeper grew somewhere to hold it, so it now arrives from
the record in one mode and from argv in the other, and `Question` is what makes
those two the same thing by the time anything thinks.

**A thinker.** `think` is a function over three seams, and the loop around it
is a function over five. A class would hold the seams as state, and nothing
needs that state to outlive a call: `serve` holds them for as long as the
process lives and hands a thinking exactly the three it uses.

**A reason on a proposal.** The record deliberately carries none, and
smuggling `said` into a proposal's parameters would write unbounded free text
into a row nothing can edit afterwards.

**A confidence.** The one refusal this project will not trade away. A number
a thinker assigns its own conclusion reads as measurement and is assertion.

`Boundary` is the nearest thing to a number that now travels, and it is the
opposite kind. It counts what was visible rather than rating what was
concluded, and it is derived from the case the inference was shown rather than
reported by whatever formed the conclusion, so nothing can inflate it.

## Where the vocabulary is the keeper's, and why that is not a leak

`Propose` carries an `operation_id`, and a case is keyed by ids the keeper
minted. That is deliberate. A proposal is refused unless its parameters satisfy
the schema its operation declares, so an id this package renamed would be an id it had
to translate back before anything could act on it, and the translation would
be the only thing the new name bought.

What would be a leak is a wire format, a route, a status code or a header
reaching the core. None does. The test that keeps it that way is
`tests/test_the_core_names_no_seam.py`.
