"""A command class name mechanically derives the event class it emits.

The rule, for a slice that emits exactly one event:

    <Verb><Subject...>   ->   <Subject...><VerbPastParticiple>

Move the leading verb to the end, put it in the past participle, and
keep every other token unchanged AND IN ORDER.

The comparison is positional, deliberately. R3 in docs/reference/naming.md
is noun-LAST, and that page records it as the rule most often read
backwards. A check that accepted the tokens in any order would be blind
to exactly the mistake it exists to catch.

## Why derivability is worth pinning

The command and the event are the same fact told twice: once as a request
that may be refused, once as a record that cannot be. When the two names
drift apart, a reader has to carry a translation table to follow one
intent through the system, and every downstream artifact inherits the
ambiguity. Keep them derivable and a reader who knows either name knows
the other.

## Scope: slices that emit exactly one event

A slice emitting two events is emitting either a cross-aggregate pair or
a state-dependent choice between them. Neither has a single event for the
command name to derive, so both are out of scope. So are query slices,
which emit nothing.

## Resolving the command class

Three strategies, in order, because a slice's command module may declare
input value objects and result types beside the command itself, so "the
first class in the file" is not safe:

  1. the handler's command-label constant, when it names a class the
     command module declares
  2. the slice directory name in Pascal case, when that class exists
  3. the sole class in the command module

## Participle stemming

Regular -ed and -en, with the three English spelling adjustments:

    silent-e restoration     relocate  ->  Relocated
    consonant de-doubling    stop      ->  Stopped
    terminal y to i          deny      ->  Denied

Irregular forms are listed one at a time in `_IRREGULAR_STEMS`. Extend
that map rather than loosening the regular rules, which is how a stemmer
starts matching unrelated words.

## Deviation policy

Two allowlists, deliberately separate, and both empty.

`_SANCTIONED_DEVIATIONS` holds pairs that are correct as they stand and
should never be "fixed". `_KNOWN_DRIFT` holds pairs judged wrong, each
recorded with the intended rename, so the backlog lives in code rather
than in a document nobody reopens.

They are split now, while both are empty, because collapsing them is
what lets drift calcify: an entry with a plausible reason beside it stops
looking like work. Splitting after the entries arrive does not happen.

Both are guarded below: an entry whose slice now derives cleanly fails,
so a rename cannot leave a dead entry behind.
"""

import ast
import re
from functools import cache
from pathlib import Path

import pytest

from tests.architecture.conftest import AROC_ROOT, tracked_python_files

pytestmark = pytest.mark.architecture

_TOKEN_RE = re.compile(r"[A-Z][a-z0-9]*")

_IRREGULAR_STEMS: dict[str, str] = {
    "held": "hold",
    "bound": "bind",
    "unbound": "unbind",
    "withdrawn": "withdraw",
    "taken": "take",
    "forgotten": "forget",
}
"""Past participle to base verb, for forms no suffix rule reaches."""

_SANCTIONED_DEVIATIONS: dict[str, str] = {}
"""Pairs that are correct as they stand. Key is bc/slice, value is why."""

_KNOWN_DRIFT: dict[str, str] = {}
"""Pairs judged wrong. Key is bc/slice, value is the intended rename."""


def _stems(token: str) -> frozenset[str]:
    """Every plausible base form of one capitalised token, lower-cased."""
    word = token.lower()
    if word in _IRREGULAR_STEMS:
        return frozenset({word, _IRREGULAR_STEMS[word]})
    out = {word}
    for suffix in ("ed", "en"):
        if word.endswith(suffix) and len(word) > len(suffix) + 1:
            base = word[: -len(suffix)]
            out |= {base, base + "e"}
            if len(base) > 2 and base[-1] == base[-2]:
                out.add(base[:-1])
            if base.endswith("i"):
                out.add(base[:-1] + "y")
    if word.endswith("e"):
        out.add(word[:-1])
    if word.endswith("y"):
        out.add(word[:-1] + "i")
    return frozenset(out)


def _derives(command: str, event: str) -> bool:
    """True when moving the command's leading verb to the end yields the event."""
    command_tokens = _TOKEN_RE.findall(command)
    event_tokens = _TOKEN_RE.findall(event)
    if not command_tokens or not event_tokens:
        return False
    verb, rest = command_tokens[0], command_tokens[1:]
    verb_stems = _stems(verb)
    for index, token in enumerate(event_tokens):
        remainder = event_tokens[:index] + event_tokens[index + 1 :]
        if _stems(token) & verb_stems and remainder == rest:
            return True
    return False


@cache
def _event_class_names() -> frozenset[str]:
    """Every class named by an event union across the tracked tree."""
    names: set[str] = set()
    for path in sorted(tracked_python_files()):
        if path.stem != "events" or "aggregates" not in path.parts:
            continue
        tree = ast.parse(path.read_text())
        union: list[str] | None = None
        for node in tree.body:
            if not isinstance(node, ast.Assign | ast.AnnAssign):
                continue
            target = node.target if isinstance(node, ast.AnnAssign) else node.targets[0]
            value = node.value
            if value is None or not isinstance(target, ast.Name):
                continue
            if target.id.endswith("Event"):
                union = [n.id for n in ast.walk(value) if isinstance(n, ast.Name)]
        if union is None:
            union = [n.name for n in tree.body if isinstance(n, ast.ClassDef)]
        names |= set(union)
    return frozenset(names)


@cache
def _command_slices() -> tuple[Path, ...]:
    """Slice directories that declare a command module, sorted by path."""
    return tuple(
        sorted(
            path.parent
            for path in tracked_python_files()
            if path.stem == "command" and path.parent.parent.name == "features"
        )
    )


def _slice_key(slice_dir: Path) -> str:
    """The bc/slice label used by the allowlists and by the test ids."""
    return f"{slice_dir.relative_to(AROC_ROOT).parts[0]}/{slice_dir.name}"


def _command_class(slice_dir: Path) -> str | None:
    """Resolve the slice's command class by the three documented strategies."""
    declared = [
        node.name
        for node in ast.parse((slice_dir / "command.py").read_text()).body
        if isinstance(node, ast.ClassDef)
    ]
    handler = slice_dir / "handler.py"
    if handler.exists():
        for node in ast.walk(ast.parse(handler.read_text())):
            if (
                isinstance(node, ast.Assign)
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id == "_COMMAND_NAME"
                and isinstance(node.value, ast.Constant)
                and node.value.value in declared
            ):
                return str(node.value.value)
    from_directory = "".join(word.capitalize() for word in slice_dir.name.split("_"))
    if from_directory in declared:
        return from_directory
    return declared[0] if len(declared) == 1 else None


def _emitted_event_classes(slice_dir: Path) -> frozenset[str]:
    """Event classes constructed anywhere inside one slice directory."""
    known = _event_class_names()
    found: set[str] = set()
    for path in sorted(tracked_python_files()):
        if not path.is_relative_to(slice_dir):
            continue
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in known
            ):
                found.add(node.func.id)
    return frozenset(found)


@cache
def _single_event_slices() -> dict[str, tuple[str, str]]:
    """Map bc/slice to its command class and its sole emitted event class."""
    out: dict[str, tuple[str, str]] = {}
    for slice_dir in _command_slices():
        emitted = _emitted_event_classes(slice_dir)
        command = _command_class(slice_dir)
        if command is None or len(emitted) != 1:
            continue
        out[_slice_key(slice_dir)] = (command, next(iter(emitted)))
    return out


def test_every_command_slice_resolves_a_command_class() -> None:
    unresolved = [_slice_key(d) for d in _command_slices() if _command_class(d) is None]
    assert not unresolved, (
        "These slices declare a command module but no class could be resolved by "
        f"any of the three documented strategies: {unresolved}. Name the class "
        "after the slice directory, or have the handler's command-label constant "
        "name it, or reduce the command module to a single class."
    )


@pytest.mark.parametrize("key", sorted(_single_event_slices()))
def test_a_command_name_derives_the_event_it_emits(key: str) -> None:
    command, event = _single_event_slices()[key]
    if key in _SANCTIONED_DEVIATIONS or key in _KNOWN_DRIFT:
        pytest.skip(f"allowlisted: {_SANCTIONED_DEVIATIONS.get(key) or _KNOWN_DRIFT[key]}")
    assert _derives(command, event), (
        f"{key}: the command {command!r} does not derive the event {event!r}. Move "
        "the leading verb to the end, put it in the past participle, and keep "
        "every other token unchanged and in order. Rename one side to match the "
        "other, or record the pair in _SANCTIONED_DEVIATIONS (correct as-is, with "
        "the reason) or _KNOWN_DRIFT (wrong, with the intended rename)."
    )


@pytest.mark.parametrize("key", sorted(_SANCTIONED_DEVIATIONS | _KNOWN_DRIFT))
def test_an_allowlisted_pair_still_fails_to_derive(key: str) -> None:
    """Drift catcher: an entry that now derives cleanly must be pruned."""
    resolved = _single_event_slices()
    assert key in resolved, (
        f"Allowlist entry {key!r} no longer resolves to a single-event command "
        "slice. It was removed, renamed, or now emits a different number of "
        "events. Update or prune the entry."
    )
    command, event = resolved[key]
    assert not _derives(command, event), (
        f"Allowlist entry {key!r} now derives cleanly ({command!r} -> {event!r}). "
        "Remove it so the pair stays enforced from here on."
    )
