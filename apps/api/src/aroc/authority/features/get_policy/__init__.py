"""The get_policy slice, re-exported so callers read `get_policy.bind`."""

from aroc.authority.features.get_policy.handler import Handler, bind
from aroc.authority.features.get_policy.query import GetPolicy
from aroc.authority.features.get_policy.route import router

__all__ = [
    "GetPolicy",
    "Handler",
    "bind",
    "router",
]
