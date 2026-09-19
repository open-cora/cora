"""The fail_run slice, re-exported so callers read `fail_run.bind`."""

from aroc.execution.features.fail_run.command import FailRun
from aroc.execution.features.fail_run.decider import decide
from aroc.execution.features.fail_run.handler import Handler, bind
from aroc.execution.features.fail_run.route import router

__all__ = [
    "FailRun",
    "Handler",
    "bind",
    "decide",
    "router",
]
