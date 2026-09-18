"""Authorize a command by asking the configured policy.

The real implementation of the `Authorize` port. Deny-by-default: a
(principal, command) pair the policy does not hold is refused, so the
rulebook says what may happen rather than what may not.

## What switching to this adapter costs

The system principal is refused everything. It cannot hold a permission,
because both writing paths refuse to grant it one, so the membership
test below simply never matches it. No branch does that; it falls out of
the model, and it is the whole point: under `AllowAllAuthorize` an
unauthenticated request runs as the system principal and is permitted
everything, and under this adapter it is permitted nothing.

That makes the cutover one-way through the API. A deployment authors its
first policy under `AllowAllAuthorize`, sets `AUTHZ_POLICY_ID`, and
restarts. It cannot author one afterwards, because defining a policy is
itself a command this adapter would deny.

## A configured policy that does not exist

Denied, every command, with the reason naming no policy at all. The
alternative, treating a missing policy as absent authorization and
allowing, would turn a typo in one environment variable into an open
door. This direction turns the same typo into an outage, which is the
failure an operator can see and fix.

## Why there is no cache

The policy is folded from its stream on every call, so an authorization
decision is one small read. `aroc.authority.aggregates.policy.read` says
why: a policy is a handful of rows, and a cache is not a line of code
but an invalidation story. When one is needed, a grant that the next
request does not see is the bug it has to be designed against, and
`test_a_grant_is_visible_to_the_very_next_decision` is the test that
will fail first.
"""

from uuid import UUID

import asyncpg

from aroc.authority.aggregates.policy import Permission, load_policy
from aroc.infrastructure.logging import get_logger
from aroc.infrastructure.ports import Allow, AllowAllAuthorize, Authorize, Deny
from aroc.infrastructure.ports.authorize import AuthzResult
from aroc.infrastructure.ports.clock import Clock
from aroc.infrastructure.ports.event_store import EventStore
from aroc.infrastructure.settings import Settings
from aroc.shared.reserved_ids import NIL_SENTINEL_ID

_log = get_logger(__name__)


class PolicyAuthorize:
    """Allow a command when the configured policy holds the exact pair."""

    def __init__(self, event_store: EventStore, policy_id: UUID) -> None:
        self._event_store = event_store
        self._policy_id = policy_id

    async def authorize(
        self,
        principal_id: UUID,
        command_name: str,
        surface_id: UUID = NIL_SENTINEL_ID,
    ) -> AuthzResult:
        """Decide one command.

        `surface_id` is accepted and not consulted. No aggregate models a
        surface, so a policy cannot yet say "this principal, this
        command, but only over HTTP". Taking the argument and ignoring it
        is what lets that arrive as a change to this adapter rather than
        as a change to every call site.

        The denial reason names the command and never the policy. A
        caller already knows which command they sent, and the policy id
        is deployment detail that would be going to somebody this
        deployment has just refused. It goes to the log instead.
        """
        policy = await load_policy(self._event_store, self._policy_id)
        if policy is None:
            _log.error(
                "authz.policy_missing",
                policy_id=str(self._policy_id),
                command_name=command_name,
                principal_id=str(principal_id),
            )
            return Deny(reason="no policy is configured for this deployment")

        if Permission(principal_id=principal_id, command_name=command_name) in policy.permissions:
            return Allow()

        _log.info(
            "authz.denied",
            policy_id=str(self._policy_id),
            command_name=command_name,
            principal_id=str(principal_id),
            surface_id=str(surface_id),
        )
        return Deny(reason=f"not permitted to issue {command_name}")


def build_authorize(
    settings: Settings,
    event_store: EventStore,
    *,
    pool: asyncpg.Pool | None,
    clock: Clock,
) -> Authorize:
    """Build the authorization adapter this deployment should run.

    Satisfies `AuthorizeFactory`, which is why `pool` and `clock` are
    named and unused: a policy is folded through the event store like
    any other aggregate, so neither is needed, and the port's docstring
    asks that being handed an argument and ignoring it be written down
    rather than absorbed by a catch-all.

    Returns `AllowAllAuthorize` when no policy is configured. That is
    the bootstrap and the local-development posture, and it is refused
    on a production tier by `build_kernel`, not here: a factory that
    knew which tiers were permissive would be a second place deciding
    what this deployment is.
    """
    _ = (pool, clock)
    if settings.authz_policy_id is None:
        return AllowAllAuthorize()
    return PolicyAuthorize(event_store, settings.authz_policy_id)


__all__ = ["PolicyAuthorize", "build_authorize"]
