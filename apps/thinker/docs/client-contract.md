# Client contract

*What this client asks of the keeper, and what it may not assume.*

The keeper has clients that are not part of it. The reporter watches an
engine and records what it sees. The conductor composes a procedure
and drives a beamline through it. This project reads an execution back and advises
what to run next. None of them imports `keeper`, nothing in the keeper imports any
of them, and they do not import each other.

A page of this name in the conductor and the reporter settles a different question:
how those two name the same run, and the two metadata keys that join an
engine's run to a keeper step. This project is not party to that agreement and
carries no copy of it, because a thinker never speaks to an engine. It reads
records the keeper already holds and writes one the keeper already has a place for,
which is the whole of its contract.

## Eight routes, seven verbs

| verb | route | what it is for |
| --- | --- | --- |
| take | `GET /inquiries?status=Open&limit=1&wait=` | find a question nobody has taken up, waiting for one if none is there |
| read | `GET /executions/{execution_id}` | how far the walk got, and what became of each step it reported |
| read | `GET /procedures/{procedure_id}` | what the steps were, which the execution's record does not say |
| ask | `POST /inquiries` | put a question, when this thinker is the one asking |
| question | `GET /inquiries/{inquiry_id}` | read back a question somebody else put |
| claim | `POST /inquiries/{inquiry_id}/claim` | say this thinker has it, and hear whether it does |
| answer | `POST /inquiries/{inquiry_id}/answer` | write the conclusion and how much was seen |
| propose | `POST /proposals` | put a run forward |

Reading is two requests because the keeper answers in two places, and it is right
that it does: an execution is a traversal and a procedure is the routine traversed,
and one procedure has many executions.

The second request is made even though an execution's response carries
`procedure_name`, and the name is then read off the procedure rather than off the
execution. It is the same string from two records, and taking it from the record
the steps came from means the name and the steps cannot disagree about which
procedure this case is about.

The seven are not symmetric, and the seams say so. One reads records the keeper
already holds, over the two routes above. Five concern an inquiry, which is the
record of somebody asking and of what came back. One puts a run forward.

An adapter that can read and not write was once described here as a dry run, and
that is no longer what it is. A thinking ends in a record whichever conclusion it
reaches, so an implementation that cannot write cannot finish, and the honest way
to look without recording is not to open an inquiry at all.

All seven are translation and none is judgement. The reading verb hands back the
two halves keyed the way the keeper keys them, and pairing them is the core's act,
not an adapter's. How much of the execution was covered is counted from the case
on the near side and handed out as a `Boundary`, so an adapter reports the
observation rather than deciding it.

The objective does cross now, in both directions, and that is the one line here
the inquiry changed. Nothing in an execution says what it was for, which is still
true; an inquiry does, which is why one verb sends the objective out and another
reads it back.

## The join key is the keeper's, not this project's

An execution step carries `procedure_step_id` and a procedure step carries
`step_id`, and those are what pair. The keeper's own route says so in both
directions: the procedure's says `step_id` is what a reader comparing a traversal
against the routine it came from joins on, and the execution's says to read the
procedure to learn what a step was asked to do.

The same instruction has a second half, and this project obeys it. An execution
step also carries `describes`, a rendering of the step for a person, and the keeper
says none of the step's detail should be recovered by taking it apart. What a step
asked for is therefore read from the procedure and `describes` is not parsed.

## Null and `Skipped` are two answers

The keeper's execution response is explicit that a null outcome means nothing was
ever said about the step, which is what a driver that died leaves behind, and that
`Skipped` means the execution reached the decision and passed it over. Both survive
into a case unchanged. A client that mapped either onto the other would be
answering a question the keeper deliberately left in two parts.

## What a thinker is when it gets there

An actor with a credential, the same way a person is. The proposal carries an operation
and parameters and nothing about who is proposing: the keeper reads that off the
authenticated principal, so the token in the configuration is what a thinker
advises as, and revoking it is how a facility stops one advising.

Nothing about a proposal says a thinker made it. That is the keeper's record to
change if a facility wants to tell machine advice from human advice, and it is not
something this project can assert from outside.

## No idempotency key, deliberately

The keeper accepts one on a proposal and this client does not send it.

Two thinkings over one execution are two acts of advising rather than one retried.
Collapsing them would hide a thinker that had thought twice, which is the thing a
reviewer most wants to see.

A loop does not change that, because it never retries a thinking. What it retries is
a turn: a failure means nothing was written, so the next attempt is a fresh claim on
a question still open, and there is no half-written act for a key to make whole. A
thinker that has already proposed has already finished.

## The four questions any keeper client meets

The reporter settled them first. A second client should answer them the same way or
say why not, and this one differs on three of the four.

| question | the reporter's answer | this project's |
| --- | --- | --- |
| how is a repeated send made safe | derive an idempotency key from the thing itself | it is not; a second thinking is a second act |
| what does a 409 mean | usually that the work is already done, not an error | on a claim, that another thinker holds the question: it comes back False rather than raising. Everywhere else it is a refusal like any other |
| which refusals are worth retrying | 5xx and 429; everything else will fail identically | none within a thinking. A thinker serving retries the whole turn, without classifying what went wrong |
| when to raise instead of report | raise means "ask me again", an outcome means "finished with" | the same, and everything raises: there is no outcome record to write a failure into |

The difference in each row is the same difference, and it is now about the thinking
rather than about the process. A thinking is one act with a record at the end of it,
so a refusal part way through means the act did not happen and there is nothing to
reconcile. What differs is only who hears about it: a person, when they ran the
command, and a log and the next turn, when nobody did.

A thinker serving is a daemon like the other two, and it answers the daemon's
question the daemon's way: anything raised is waited out and tried again, with no
judgement about which failures deserve it. What it does not do is what a retry
policy usually buys, which is making a half-finished act safe to repeat. There is
no half-finished act here.

## What this page does not promise

**That a proposal is a good idea.** The keeper checks that parameters satisfy the
operation's schema and nothing checks anything else. A proposal is a suggestion that was
found runnable, not one that was found sound.

**That the case is complete.** An execution's record holds what somebody reported,
and a driver that died between a step and its report leaves a gap one step wide.
The gap is visible in the case and is not filled in.

**That a conclusion can be traced back to a proposal.** The proposal record carries
no reason and no reference to the thinking that produced it. The inquiry names the
proposal, which is the link in that direction; the other direction is not written
down anywhere, and used to be covered by a person having run the thinker and read
the output. Nobody reads the output of a thinker that finds its own work.
