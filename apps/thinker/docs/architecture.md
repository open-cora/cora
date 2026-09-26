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

`apps/conductor` pairs its own two halves inside its adapter and is right to:
it says both are built from one response, in one pass, with no second writer
to drift against. Here they are two responses from two routes, which is the
case that reasoning excludes.

## The objects

| Object | Where | What it is | What it is not |
| --- | --- | --- | --- |
| `Reading` | `case.py` | the two halves as a record hands them over, keyed and unpaired | a case, and not anything to judge |
| `Case` | `case.py` | one execution, every intent paired with what became of it, plus the objective | a claim that any of it succeeded |
| `Step` | `case.py` | one thing meant to happen, and what became of it | a keeper procedure step, reshaped |
| `Conclusion` | `conclusions.py` | one of four judgements, as four classes | a verdict string, and never a score |
| `Thought` | `think.py` | one thinking end to end: read, concluded, written | a record of anything |
| `ThinkerConfig` | `config.py` | where the keeper is, who this is when it gets there, what builds an inference | a place for model settings |

`Reading` and `Case` are the pair worth understanding together. A reading is
what was read; a case is what it means once the halves are put against each
other. The seam produces the first and only `assemble` produces the second,
so there is exactly one way for a case to come into being.

## One invocation, object by object

Nothing below is a loop and nothing below is a server. A thinker is handed an
execution id, and these are the objects that exist between that and the exit
status.

```
  argv                              thinker.toml
  --config thinker.toml             [keeper]    base_url, token
  --execution exec-1                [inference] profile
  --objective "find the edge"
         \                                /
          v                              v
        __main__.main()
            |
            |  load(path) .......................... ThinkerConfig
            |  inference_for(config) ............... Inference      (else exit 2)
            |  HttpKeeper(http, base_url, token) ... Keeper
            |
            v
        think("exec-1", keeper=, inference=, objective="find the edge")
            |
   read     |  keeper.read("exec-1")
            |      GET /executions/exec-1           the record
            |      GET /procedures/proc-1           the intent
            |      |
            |      v
            |  Reading(
            |      asked  = [("s1", {...}), ("s2", {...})]  ordered, a procedure is
            |      became = {"s1": "Done", "s2": None}      keyed, the record cites
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
   advise   |  if Propose:  keeper.propose(plan_id, parameters)
            |                   POST /proposals  ->  proposal_id
            v
        Thought(case, conclusion, proposal_id)
            |
            v
        stdout, as JSON, exit 0
```

The write is last and covers one arm, which is the right way round: a thinker
that dies partway through has advised nothing, and a conclusion nobody heard
costs a re-run where a proposal nobody concluded costs a beamline's time.

The case travels back beside the conclusion for a related reason. A conclusion
is only as good as the case behind it, and the commonest way for one to be
wrong is for the case to be thinner than its reader assumed.

Only a configuration that will not load is caught on that path. A keeper that
cannot be reached ends the run with a status of 1, and a provider that raised
ends it with a traceback. Neither becomes `Abstain`. The status says whether
the thinker ran and never what it concluded, so all four conclusions are 0.

## The join, and what a join by position would do

The pairing `assemble` performs, on the key the keeper names on both sides:

```
        asked                      joined on              became
   ordered, the procedure's         the id           keyed, the record's
   -----------------------          ------           -------------------

   ("s1", {move motor:x 1.5})  <---- "s1" ---->  "Done"
   ("s2", {acquire plan-9})    <---- "s2" ---->  None       reported, no outcome
   ("s3", {move motor:x 2.0})  <---- "s3" ---->  absent     never reached at all

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

**A seam is named for what the outside thing is to this one.** `Keeper` keeps
the record, `Inference` infers. Neither takes a `Port` suffix, since
everything in that module is a seam and saying so distinguishes nothing.

**A field is named for the act, not for the schema it came out of.** `asked`
and `became` rather than `procedure_step` and `outcome`. The pair reads as a
sentence about one step, and neither name survives being read as the other.

**A distinction worth drawing is a class, not a field.** Four conclusions are
four classes, because a field can be set wrong and a class cannot, and
whatever reads one keys off the class instead of parsing a word.

**`None` means the record is silent.** It is never a value the record could
have given and never a default standing in for one. A step whose `became` is
`None` was not reported on, which is a different fact from every outcome the
keeper has a word for.

## What is deliberately not an object

**An objective.** Free text on the case. It is the caller's question, not a
structure this package has any business validating, and nothing yet reads it
except whatever does the thinking.

**A thinker.** `think` is a function over two seams. A class would hold the
seams as state, and there is no second call for that state to serve: a
thinker is invoked, thinks once, and exits.

**A reason on a proposal.** The record deliberately carries none, and
smuggling `said` into a proposal's parameters would write unbounded free text
into a row nothing can edit afterwards.

**A confidence.** The one refusal this project will not trade away. A number
a thinker assigns its own conclusion reads as measurement and is assertion.

## Where the vocabulary is the keeper's, and why that is not a leak

`Propose` carries a `plan_id`, and a case is keyed by ids the keeper minted.
That is deliberate. A proposal is refused unless its parameters satisfy the
schema its plan declares, so an id this package renamed would be an id it had
to translate back before anything could act on it, and the translation would
be the only thing the new name bought.

What would be a leak is a wire format, a route, a status code or a header
reaching the core. None does. The test that keeps it that way is
`tests/test_the_core_names_no_seam.py`.
