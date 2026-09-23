"""The plans blueapi is pointed at, and the one simulated detector they read.

No `deviceManager` source, which is itself worth recording: blueapi's
device sources want a dodal-style manager, and a plan that names no
device parameter needs none of that. So this module is a plain Python
file on `PYTHONPATH` with two functions in it, which is the smallest
deployment the service accepts.

The detector is `ophyd.sim.det`, built at import. It is not a parameter
of either plan, so nothing here depends on how blueapi resolves device
names, which is a separate question this spike does not ask.
"""

from bluesky.plans import count
from bluesky.utils import MsgGenerator
from ophyd.sim import det


def quick_count(num: int = 1) -> MsgGenerator:
    """One run that ends almost at once, for the questions about identity."""
    yield from count([det], num=num)


def slow_count(num: int = 6, delay: float = 0.5) -> MsgGenerator:
    """One run that lasts long enough for a second client to collide with it.

    Three seconds by default. Question 1 asks what the service tells a
    caller that arrives while this is still going, and a plan that ended
    before the second request landed would answer it by construction.
    """
    yield from count([det], num=num, delay=delay)


def failing_count(num: int = 2) -> MsgGenerator:
    """A run that opens, reads, and then raises inside the plan.

    Question 5 is whether the plan-level outcome and the run-level
    `exit_status` agree, and a plan that only ever succeeds answers it for
    one case out of two. This raises after the run is open, so there is a
    start document to disagree about.
    """
    yield from count([det], num=num)
    raise RuntimeError("the spike asked this plan to fail")
