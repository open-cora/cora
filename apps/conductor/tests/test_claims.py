"""A claim names what the IOC serves, and coverage is not a string prefix."""

from __future__ import annotations

import pytest

from conductor.claims import (
    Claim,
    ClaimConflictError,
    InvalidScopeError,
    Ledger,
    Scope,
)


def test_record_scope_with_a_field_suffix_names_the_record() -> None:
    assert Scope.record("2bmb:m1.VAL") == Scope.record("2bmb:m1")


def test_record_scopes_for_two_fields_of_one_motor_conflict() -> None:
    assert Scope.record("2bmb:m1.VAL").conflicts_with(Scope.record("2bmb:m1.STOP"))


def test_record_scope_does_not_cover_a_longer_name_sharing_its_prefix() -> None:
    """The trap a `startswith` test would fall into: m1 and m10 are two motors."""
    assert not Scope.record("2bmb:m1").conflicts_with(Scope.record("2bmb:m10"))


def test_namespace_scope_covers_a_record_beneath_it() -> None:
    assert Scope.namespace("2bmb:cam1:").covers(Scope.record("2bmb:cam1:Acquire"))


def test_namespace_scope_does_not_cover_a_sibling_namespace() -> None:
    assert not Scope.namespace("2bmb:cam1:").conflicts_with(Scope.namespace("2bmb:cam2:"))


def test_namespace_scope_conflicts_with_a_record_beneath_it_in_either_order() -> None:
    namespace = Scope.namespace("2bmb:")
    record = Scope.record("2bmb:m1")
    assert namespace.conflicts_with(record)
    assert record.conflicts_with(namespace)


def test_parse_reads_a_trailing_separator_as_a_namespace() -> None:
    assert Scope.parse("2bmb:cam1:").covers_beneath
    assert not Scope.parse("2bmb:m1").covers_beneath


def test_scope_built_from_nothing_is_refused() -> None:
    with pytest.raises(InvalidScopeError):
        Scope.record("   ")


def test_claim_overlap_names_the_colliding_scope_rather_than_a_boolean() -> None:
    mine = Claim.over("2bmb:m1", "2bmb:m2")
    theirs = Claim.over("2bmb:m2.RBV", "2bmb:m3")
    assert mine.overlap(theirs) == frozenset({Scope.record("2bmb:m2")})


def test_claims_over_different_motors_do_not_conflict() -> None:
    assert not Claim.over("2bmb:m1").conflicts_with(Claim.over("2bmb:m10", "2bmb:m2"))


def test_ledger_grants_a_claim_nothing_else_holds() -> None:
    ledger = Ledger()
    ledger.acquire("first", Claim.over("2bmb:m1"))
    assert ledger.holders() == frozenset({"first"})


def test_ledger_refuses_a_claim_another_holder_overlaps() -> None:
    ledger = Ledger()
    ledger.acquire("scan", Claim.over("2bmb:m1"))
    with pytest.raises(ClaimConflictError) as refused:
        ledger.acquire("nudge", Claim.over("2bmb:m1.VAL"))
    assert refused.value.holder == "scan"
    assert refused.value.overlap == frozenset({Scope.record("2bmb:m1")})


def test_ledger_grants_a_claim_over_untouched_hardware() -> None:
    ledger = Ledger()
    ledger.acquire("scan", Claim.over("2bmb:m1"))
    ledger.acquire("nudge", Claim.over("2bmb:m2"))
    assert ledger.holders() == frozenset({"scan", "nudge"})


def test_ledger_releases_what_a_holder_had() -> None:
    ledger = Ledger()
    ledger.acquire("scan", Claim.over("2bmb:m1"))
    ledger.release("scan")
    ledger.acquire("nudge", Claim.over("2bmb:m1"))
    assert ledger.held_by("nudge") == Claim.over("2bmb:m1")


def test_ledger_releasing_a_holder_that_holds_nothing_is_not_an_error() -> None:
    Ledger().release("nobody")


def test_granted_releases_the_claim_when_the_block_raises() -> None:
    ledger = Ledger()
    with pytest.raises(ZeroDivisionError), ledger.granted("scan", Claim.over("2bmb:m1")):
        raise ZeroDivisionError
    assert ledger.holders() == frozenset()


def test_ledger_refuses_a_holder_that_already_holds_something() -> None:
    ledger = Ledger()
    ledger.acquire("scan", Claim.over("2bmb:m1"))
    with pytest.raises(ClaimConflictError):
        ledger.acquire("scan", Claim.over("2bmb:m2"))
