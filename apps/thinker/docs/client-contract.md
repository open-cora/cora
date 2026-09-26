# Client contract

*What this client asks of the keeper, and what it may not assume.*

The keeper has clients that are not part of it. The reporter watches an
acquisition engine and records what it sees. The conductor composes a procedure
and drives a beamline through it. This project reads an execution back and advises
what to run next. None of them imports `keeper`, nothing in the keeper imports any
of them, and they do not import each other.

A page of this name in the conductor and the reporter settles a different question:
how those two name the same acquisition, and the two metadata keys that join an
engine's run to a keeper step. This project is not party to that agreement and
carries no copy of it, because a thinker never speaks to an engine. It reads
records the keeper already holds and writes one the keeper already has a place for,
which is the whole of its contract.

## Three routes, two verbs

| verb | route | what it is for |
| --- | --- | --- |
| read | `GET /executions/{execution_id}` | how far the walk got, and what became of each step it reported |
| read | `GET /procedures/{procedure_id}` | what the steps were, which the execution's record does not say |
| write | `POST /proposals` | put a run forward |

Reading is two requests because the keeper answers in two places, and it is right
that it does: an execution is a traversal and a procedure is the routine traversed,
and one procedure has many executions.

The second request is made even though an execution's response carries
`procedure_name`, and the name is then read off the procedure rather than off the
execution. It is the same string from two records, and taking it from the record
the steps came from means the name and the steps cannot disagree about which
procedure this case is about.

The two verbs are not symmetric, and the seam says so. An adapter that can read and
not write is a thinker that can look and not advise, which is a supported
arrangement rather than a broken one: it is what a dry run is.

Both are translation and neither is judgement. The reading verb hands back the two
halves keyed the way the keeper keys them, and pairing them is the core's act, not
an adapter's. Nor does either verb carry an objective: nothing in the keeper holds
what an execution was for, so asking an adapter to pass one through would be
handing it something it could only give straight back.

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

An actor with a credential, the same way a person is. The proposal carries a plan
and parameters and nothing about who is proposing: the keeper reads that off the
authenticated principal, so the token in the configuration is what a thinker
advises as, and revoking it is how a facility stops one advising.

Nothing about a proposal says a thinker made it. That is the keeper's record to
change if a facility wants to tell machine advice from human advice, and it is not
something this project can assert from outside.

## No idempotency key, deliberately

The keeper accepts one on a proposal and this client does not send it.

Two runs of a thinker over one execution are two acts of advising rather than one
retried. Collapsing them would hide a thinker that had been invoked twice, which is
the thing a reviewer most wants to see, and there is no retry here for a key to make
safe: this process makes each call once and exits, and re-invoking it is a person's
decision rather than a loop's.

## The four questions any keeper client meets

The reporter settled them first. A second client should answer them the same way or
say why not, and this one differs on three of the four for reasons that come from
being invoked rather than from being right.

| question | the reporter's answer | this project's |
| --- | --- | --- |
| how is a repeated send made safe | derive an idempotency key from the thing itself | it is not; a second invocation is a second act |
| what does a 409 mean | usually that the work is already done, not an error | nothing; the one write documents 400, 403 and 404, and any non-201 is a refusal |
| which refusals are worth retrying | 5xx and 429; everything else will fail identically | none are retried here, because the caller is still standing there |
| when to raise instead of report | raise means "ask me again", an outcome means "finished with" | the same, and everything raises: there is no outcome record to write a failure into |

The difference in each row is the same difference. A reporter and a conductor are
daemons and have to decide what to do about a keeper that is briefly unavailable. A
thinker is a command somebody ran, so the honest thing to do with a refusal is to
say it and exit, and let the person decide whether to ask again.

## What this page does not promise

**That a proposal is a good idea.** The keeper checks that parameters satisfy the
plan's schema and nothing checks anything else. A proposal is a suggestion that was
found runnable, not one that was found sound.

**That the case is complete.** An execution's record holds what somebody reported,
and a driver that died between a step and its report leaves a gap one step wide.
The gap is visible in the case and is not filled in.

**That a conclusion can be traced back to a proposal.** The proposal record carries
no reason and no reference to the thinking that produced it. What links them today
is that a person ran the thinker and read the output.
