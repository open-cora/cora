"""The report_run slice, re-exported so callers read `.bind`."""

from aroc.execution.features.report_run.command import ReportRun
from aroc.execution.features.report_run.context import ReportRunContext
from aroc.execution.features.report_run.decider import decide
from aroc.execution.features.report_run.handler import (
    Handler,
    IdempotentHandler,
    bind,
)
from aroc.execution.features.report_run.route import router

__all__ = [
    "Handler",
    "IdempotentHandler",
    "ReportRun",
    "ReportRunContext",
    "bind",
    "decide",
    "router",
]
