# Glossary

*The words this project shares with the keeper, and the few it adds.*

Every term in the first list is the keeper's, copied rather than linked, because
the two projects ship separately and a shared word that drifted would be worse than
a word written twice. The keeper's own glossary is the longer one: it also holds
the vocabulary of bounded contexts, events and projections, none of which this
project has.

A term used here and not listed is plain English.

## The work

- **Plan.** A runnable routine this system holds a record of: the name the engine knows it by, and the JSON Schema a run of it must satisfy. Defined, not registered: nothing anywhere pairs that name with that schema until the record says so.
- **Procedure.** A routine the keeper composed, written down: an ordered list of steps, each naming what it touches. The contrast with a **plan** is who authored the routine. A plan names something an engine already has and a procedure names something nothing knows until the keeper says so.
- **Step.** One element of a procedure. Two kinds: a **move**, which sends one record to one value, and an **acquisition**, which asks an engine to run a plan. What a step asked for is read from the procedure and never from the execution's rendering of it.
- **Execution.** One traversal of a procedure: the record the keeper opens when it dispatches one, and how far the thing driving it got. Every step of it is either reported by a driver or left unreported, and the record says which.
- **Execution status.** How far an execution has got: Dispatched, Claimed, Running or Ended. Derived by the keeper from which events the stream carries, never stored. Read here off the status the keeper gives and never counted from outcomes.
- **Step outcome.** What a driver reported of one step: Done, Refused, Broken or Skipped. Absent is a fifth answer and not one of the four. Skipped means the execution reached the decision and passed the step over; absent means nothing was ever said, which is what a driver that died leaves behind.
- **Proposal.** A run an agent put forward, before anything has run it: which plan, with what values, who advised it, and the acquisition that took it if one has. It cites a plan and does not contain one. A proposal refers to no act at all, which is the whole distinction between it and a step.
- **Taken.** Of a proposal: an acquisition step exists that ran what it proposed. Not **accepted**, which says a party considered it and said yes, and nobody did: whoever composed the procedure may simply have gone ahead.
- **Engine.** Whatever actually runs a routine, outside this system. Named by role rather than by product, because which one a deployment runs is a deployment's fact. Nothing here speaks to one.

## The words this project adds

Four, and each is declared in the module named beside it. They are pinned here
because they are the ones a reader arriving from the keeper or the conductor will
not recognise.

- **Reading.** The two halves of an execution as the keeper hands them over, keyed and not yet paired: what the procedure asked for, and what the record says became of each step. What the reading seam returns, and the last shape the keeper's own vocabulary reaches. Declared in `case.py`.
- **Case.** What the thinking is about: one execution, with every step the procedure composed paired against whatever the record says became of it, and the objective if there was one. Assembled from a reading, in the core rather than in an adapter, because the pairing is a decision and there is one place to make it. Declared in `case.py`.
- **Objective.** What a thinking is toward, in free text, supplied by whoever invoked the thinker. Not stored anywhere and not derivable: the keeper holds what an execution was asked to do and nothing holds what it was for. A case assembled without one is a legitimate case, and one arm of a conclusion becomes dishonest to reach from it.
- **Conclusion.** What a thinker decided: `Propose`, `Stop`, `Abstain` or `Refer`. Four classes rather than one verdict field, because a field can be set wrong and a class cannot. Only the first has a record to live in. Declared in `conclusions.py`.
- **Thinking.** One read, one conclusion and at most one write, done once and then over. The noun for the act; `Thought` is the record of it and carries the case beside the conclusion. Declared in `think.py`.

## Two words this project does not use

- **Decision.** It would claim the thinker settled something, and nothing here settles anything: a proposal is a suggestion somebody else takes up or does not. **Conclusion** claims only that the thinking finished.
- **Recommendation.** Nearer, and still too strong for three of the four arms. `Abstain` recommends nothing and `Refer` recommends only that somebody else look, so a word that fitted one arm would have to be stretched over the others.
