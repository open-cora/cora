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

## The one that is missing

There was a sixth spike, access_security, and its findings page was never
committed. It is on no branch and in no worktree. What survives on the
workstation is an IOC startup log that records nothing about what was
measured, and the ignore rules would have kept it out of here anyway.

Its conclusion lives only as prose in `beamlines/EXPANSION.md`, where two
decisions rest on it, and that page now says so at the point it makes the
claim.

It is the reason the rest of this directory is committed rather than left on
a workstation.
