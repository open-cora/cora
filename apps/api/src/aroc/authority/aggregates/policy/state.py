"""Policy state, the permission it is made of, and its domain errors.

A Policy is the rulebook one deployment authorizes against: the set of
(principal, command) pairs that are permitted. Everything not in the set
is refused, so the policy says what may happen rather than what may not.

## Why a pair, and not two lists

An earlier shape in the codebase this chassis came from held two
independent sets, the permitted principals and the permitted commands,
and checked membership in each separately. That grants every principal
every command, the whole cross product. A rulebook listing a read-only
status feed alongside a supervisor who may abort a run had granted the
feed permission to abort runs. Nothing exercised that authority, and the
rulebook still said more than the system it governed did, which is the
one artifact that must not.

Holding pairs makes the cross product unrepresentable rather than
checked. There is no test for it here because there is no way to write
the bug.

## Why there is no name

The same reasoning as the Actor's. One deployment authorizes against one
policy, selected by id in settings, so a name would be decoration on a
singleton, and a field added before a caller asks for it is shaped by
guesswork about who will read it.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from uuid import UUID

from aroc.shared.reserved_ids import SYSTEM_PRINCIPAL_ID

GOVERNING_COMMAND_NAMES: frozenset[str] = frozenset({"GrantPolicyPermission"})
"""The commands that can change a policy, named by the policy itself.

A rulebook says who may edit the rulebook, which makes it the only thing
standing between a deployment and a state nobody can repair. Revoke the
last principal permitted to grant and no one can ever add anyone again,
short of restarting the process with authorization switched off.

So a policy must always name at least one principal for each of these.
The set is declared here, on the aggregate, rather than in the slice
that issues them, because it is the AGGREGATE's rule about itself and
because a decider in one slice may not import from another.

These strings must match the `_COMMAND_NAME` a handler actually
declares, and nothing about writing them in two files makes that so.
`tests/architecture/test_governing_commands_exist.py` compares the two
sides: a governing name no handler issues would guard a command nobody
can send, and a policy could then be accepted as governable while being
a brick.

Revoking joins this set in the commit that makes revoking possible. It
is absent rather than anticipated, because a rule naming a command the
build cannot issue is the failure this check exists to catch.
"""


class PolicyNotFoundError(Exception):
    """A command named a policy id with no stream behind it."""

    def __init__(self, policy_id: UUID) -> None:
        super().__init__(f"Policy {policy_id} not found")
        self.policy_id = policy_id


class PolicyAlreadyExistsError(Exception):
    """Definition was attempted against an id that already has a stream.

    Unreachable through the ordinary path, because a defining handler
    mints a fresh id and a fresh id has no history. It exists so the
    decider states the precondition it relies on rather than assuming
    it, and so a caller supplying its own id is refused instead of
    writing a second genesis event onto a live stream.
    """

    def __init__(self, policy_id: UUID) -> None:
        super().__init__(f"Policy {policy_id} already exists")
        self.policy_id = policy_id


class SystemPrincipalCannotBeGrantedError(Exception):
    """A permission named the system principal as the party being granted.

    The system principal is the identity an unauthenticated request runs
    as under the development posture. It exists so that a deployment
    with no rulebook yet can still be operated, which is how the first
    policy gets written at all.

    It is refused as a GRANTEE, never as an author. The party that
    defines the first policy IS the system principal, recorded in the
    event envelope as having done so, and it grants that policy to real
    registered actors. Those are two different fields, and the whole
    bootstrap rests on their being different.

    What this prevents is the shortcut afterwards: granting the shared
    fallback identity a standing power, so that anything reaching the
    fallback inherits it and no audit trail says who acted. A background
    job that needs authority gets a registered actor of its own.
    """

    def __init__(self) -> None:
        super().__init__(
            "The system principal cannot be granted a permission: it is the "
            "unauthenticated fallback identity, not a party. Register an actor "
            "and grant that instead."
        )


class PolicyWouldBeUngovernableError(Exception):
    """The policy would be left with no one able to change it.

    Unrecoverable through the API by construction: the command that
    would put it right is the one nobody is permitted to issue. The only
    way back is a restart with a permissive authorization adapter, which
    on a production tier is a deploy.

    Refused rather than warned about, because the caller cannot undo it
    and neither can anybody else.
    """

    def __init__(self, missing: Iterable[str]) -> None:
        names = ", ".join(sorted(missing))
        super().__init__(
            f"A policy must permit at least one principal to issue each of: {names}. "
            "Without that, nothing can ever change it again."
        )
        self.missing = frozenset(missing)


class PolicyCannotGrantPermissionError(Exception):
    """The permission is already in the policy.

    A no-op would have been the friendlier answer and is the wrong one,
    for the reason Access gives for refusing a repeated switch: two
    operators granting what they each believe to be a new permission
    should not both be told they granted it. One of them is reading a
    stale rulebook.
    """

    def __init__(self, principal_id: UUID, command_name: str) -> None:
        super().__init__(
            f"Principal {principal_id} may already issue {command_name} under this policy"
        )
        self.principal_id = principal_id
        self.command_name = command_name


@dataclass(frozen=True)
class Permission:
    """One principal may issue one command.

    Both halves are stored as bare values with nothing checked behind
    them. `principal_id` is not looked up in Access, and `command_name`
    is not compared against the commands this build actually has, so a
    typo produces a permission that silently never matches rather than a
    refusal at write time.

    That is deliberate for now and it is the invariant people assume
    exists, so it is written down here rather than left to be
    discovered. The operational answer is the shadow posture: a
    permission naming a command nobody issues shows up as a denial in
    the shadow log before enforcement is ever switched on.

    Frozen, so it is hashable and can live in the `frozenset` that makes
    the cross-product bug from the module docstring impossible.
    """

    principal_id: UUID
    command_name: str


@dataclass(frozen=True)
class Policy:
    """The rulebook, as the fold leaves it.

    `permissions` is a set, so granting the same pair twice cannot
    produce two entries. Whether a repeat grant is REFUSED rather than
    absorbed is a decision for the slice that grants, not for the shape
    here.

    An empty set is a policy that permits nothing. That is a legitimate
    state today, because a policy cannot yet be changed after it is
    defined and repointing the deployment at a deny-all policy is how
    access gets switched off wholesale. It stops being legitimate the
    moment a policy can be edited, because a policy that permits nothing
    also permits nobody to edit it.
    """

    id: UUID
    permissions: frozenset[Permission]


def reject_the_system_principal(permissions: Iterable["Permission"]) -> None:
    """Refuse a set in which the system principal is being granted anything.

    One function rather than a line in each decider, so defining and
    granting cannot drift into disagreeing about who may hold a
    permission.
    """
    if any(p.principal_id == SYSTEM_PRINCIPAL_ID for p in permissions):
        raise SystemPrincipalCannotBeGrantedError


def ungoverned_commands(permissions: Iterable["Permission"]) -> frozenset[str]:
    """Governing commands that no permission in this set names.

    Empty means the policy can still be changed by somebody. Returns the
    missing names rather than a boolean so the refusal can say which
    power was about to be lost, which is the difference between an error
    a caller can act on and one they have to guess at.
    """
    named = {p.command_name for p in permissions}
    return GOVERNING_COMMAND_NAMES - named


__all__ = [
    "GOVERNING_COMMAND_NAMES",
    "Permission",
    "Policy",
    "PolicyAlreadyExistsError",
    "PolicyCannotGrantPermissionError",
    "PolicyNotFoundError",
    "PolicyWouldBeUngovernableError",
    "SystemPrincipalCannotBeGrantedError",
    "reject_the_system_principal",
    "ungoverned_commands",
]
