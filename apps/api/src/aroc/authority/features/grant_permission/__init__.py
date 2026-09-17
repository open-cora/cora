"""The grant_permission slice, re-exported so callers read `grant_permission.bind`."""

from aroc.authority.features.grant_permission.command import GrantPolicyPermission
from aroc.authority.features.grant_permission.decider import decide
from aroc.authority.features.grant_permission.handler import Handler, bind
from aroc.authority.features.grant_permission.route import router

__all__ = [
    "GrantPolicyPermission",
    "Handler",
    "bind",
    "decide",
    "router",
]
