"""The worker environment RE Manager opens: simulated devices, plans, a recorder.

No IOC and no Channel Access here, unlike `spikes/conductor/`. The
questions this spike asks are about the queue, the lock and the two
identities, and none of them is a question about a motor. Leaving EPICS
out also leaves out a port: two sessions sharing this checkout collided
on Channel Access 5064 once already, and a spike that needs no socket
cannot join in.

`ophyd.sim.motor` is still a device two queue items can both move, which
is all question 1 needs to make a conflict the queue may or may not
notice.

## Why the RunEngine is built here

RE Manager will make one if the startup code does not, and then nothing
is subscribed to it. Question 3 asks what reaches the start document, so
the documents have to be written down somewhere the probe can read them
after the worker process is gone. A file is the whole mechanism: this is
the same thing `apps/reporter` does with a 0MQ publisher, minus a port.
"""

import json
import os
from pathlib import Path

from bluesky import RunEngine
from bluesky.plan_stubs import mv
from bluesky.plans import count, scan  # noqa: F401
from ophyd.sim import det, motor  # noqa: F401

DOCUMENTS = Path(os.environ.get("AROC_SPIKE_DOCUMENTS", "documents.jsonl"))
"""Where start and stop documents are appended, one JSON object per line."""


def _record(name, document):
    """Append the two document types this spike reads, dropping the rest.

    Events and descriptors are the bulk of a stream and say nothing about
    identity, which is the only thing being asked here.
    """
    if name not in ("start", "stop"):
        return
    with DOCUMENTS.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({"name": name, "doc": document}, default=str) + "\n")


RE = RunEngine({})
RE.subscribe(_record)


def move_and_count(detectors, mover, target, num=1):
    """Move one device and then read another, as a single queue item.

    A stand-in for a procedure step that both moves and acquires, so two
    queue items can want the same device without either being a bare move.
    """
    yield from mv(mover, target)
    yield from count(detectors, num=num)
