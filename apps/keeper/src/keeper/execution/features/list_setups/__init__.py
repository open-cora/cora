"""The list_setups slice, re-exported so callers read `list_setups.bind`."""

from keeper.execution.features.list_setups.handler import Handler, bind
from keeper.execution.features.list_setups.query import (
    DEFAULT_PAGE_SIZE,
    MAX_PAGE_SIZE,
    ListSetups,
)
from keeper.execution.features.list_setups.route import router

__all__ = [
    "DEFAULT_PAGE_SIZE",
    "MAX_PAGE_SIZE",
    "Handler",
    "ListSetups",
    "bind",
    "router",
]
