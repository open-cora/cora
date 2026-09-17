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

from dataclasses import dataclass
from uuid import UUID


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


__all__ = [
    "Permission",
    "Policy",
    "PolicyAlreadyExistsError",
    "PolicyNotFoundError",
]
