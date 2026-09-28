# Spikes

Programs written to settle one question against real software, kept because
prose elsewhere in this tree argues from the answers.

A spike is evidence, not maintained code. Nothing imports one, no lane runs
one, and none of them is expected to work against today's dependencies. What
each is expected to do is say what was measured and what was run against:
every `FINDINGS.md` names its versions in its opening lines.

| Spike | The question it settled |
| --- | --- |
| `spikes/bluesky_adapter/` | What one engine's document stream can and cannot say about a run |
| `spikes/tomoscan_adapter/` | Whether the run model is general, or one engine's model well named |
| `spikes/conductor/` | What two writers on one device do to a scan |
| `spikes/ophyd_adapter/` | Whether a device object is a safe unit to claim |
| `spikes/tiled_adapter/` | What a store can be asked about data it is holding |

## What has been edited since they were written

Paths only. These were written when the keeper was `apps/api` and before the
documentation moved inside each project, so citations that named a real file
then named nothing afterwards. Those have been requalified against the
current tree, and the root tier's `tests/test_every_cited_path_resolves.py`
is what keeps them honest from here.

No measurement, number, table or conclusion has been touched. Where a spike
cites a file in somebody else's package, the citation is left exactly as it
was, because it was never a claim about this tree.

One reference could not be requalified. The conductor's findings argued from
an invariant held by the Run aggregate, and that aggregate has since been
retired, so the sentence names it rather than pointing at a file that is not
there.

## The sixth, and why it stays out

There is a sixth spike, access_security, and it is not missing. It was
committed here, taken out again deliberately, and its findings page is still
in the history: `git log --diff-filter=D` over that directory finds the change
that removed it, and all 169 lines come back from the commit before.

This section said the opposite three times over, and the expansion plan said
it once, and neither had tried to retrieve the thing. A statement that
evidence is gone is a claim like any other and this one was refutable in a
single command. There is an irony worth keeping: the belief that a page had
been lost is what got the other five committed, and the belief was wrong.

**Why it stays out, which was written down nowhere until now.** It carries an
access-security file and a records database from a real beamline. Those
describe how one facility's controllers decide who may write to what, and
publishing them is not this repository's to do. The exclusion is right and
should stay. That is worth saying plainly, because the next person to notice
a gap in the numbering will otherwise be tempted to close it, and the reason
being absent is exactly what makes restoring it look like a tidy-up.

Nothing of that kind is in the five that are here.

The conclusion it reached is quoted where it is used, and now that the page
is known to be retrievable, anything resting on more than the quoted sentence
can be checked against it rather than measured again.
