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

## Scope: slices whose command names one event

A slice emitting one event class is in scope, and that class is the one
its command name has to derive.

A slice emitting several is in scope when exactly one of them is built on
every path through the function that builds it. That one is the act the
command asked for, and the others are facts the act may or may not bring
with it. Dispatching an execution is the case: it always emits its genesis
and adds the setups it pinned only when a step takes one, so
`DispatchExecution` still names `ExecutionDispatched`, and a rename of
either side is still a rename this rule has to see.

The two shapes that stay out have no single event for the command name to
derive. A cross-aggregate pair is built together, so more than one class
is built on every path; a state-dependent choice builds each class on a
branch of its own, so none is. Query slices emit nothing.

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

## No exceptions

There is no allowlist. A pair that does not derive is renamed on one
side or the other, because that is the only fix that leaves a reader
able to guess either name from the other, which is the whole point.

An allowlist would be for a pair that cannot be renamed, and the reason
a name cannot be changed is always that something outside this
repository depends on it. Nothing does yet. When something does, the
exception arrives with the constraint that forced it.
"""

import ast
import re
from functools import cache
from pathlib import Path

import pytest

from tests.architecture.conftest import KEEPER_ROOT, tracked_python_files

pytestmark = pytest.mark.architecture

_TOKEN_RE = re.compile(r"[A-Z][a-z0-9]*")

_IRREGULAR_STEMS: dict[str, str] = {
    "held": "hold",
    "made": "make",
    "bound": "bind",
    "unbound": "unbind",
    "withdrawn": "withdraw",
    "taken": "take",
    "forgotten": "forget",
}
"""Past participle to base verb, for forms no suffix rule reaches."""


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
    """True when moving the command's leading verb to the end yields the event.

    The verb must be the LAST token of the event, not merely present in
    it. An earlier version scanned every position, which accepted
    `RegisterActor -> RegisteredActor`: the tokens are all there and the
    remainder matches, so only position tells the two apart. Position is
    the whole of R3.

    Tense is not checked here. `ActorRegister` has its verb last and
    passes this rule; `test_event_class_name_shape` is what refuses it
    for not being in the past. Splitting them keeps each failure message
    about one thing.
    """
    command_tokens = _TOKEN_RE.findall(command)
    event_tokens = _TOKEN_RE.findall(event)
    if not command_tokens or not event_tokens:
        return False
    verb, rest = command_tokens[0], command_tokens[1:]
    return bool(_stems(event_tokens[-1]) & _stems(verb)) and event_tokens[:-1] == rest


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
    return f"{slice_dir.relative_to(KEEPER_ROOT).parts[0]}/{slice_dir.name}"


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


_CONDITIONAL = (
    ast.If,
    ast.IfExp,
    ast.Match,
    ast.For,
    ast.AsyncFor,
    ast.While,
    ast.ExceptHandler,
    ast.ListComp,
    ast.SetComp,
    ast.DictComp,
    ast.GeneratorExp,
    ast.BoolOp,
    ast.Lambda,
)
"""Nodes that can leave whatever sits under them unbuilt on some path."""


def _built_on_every_path(source: str, known: frozenset[str]) -> frozenset[str]:
    """Event classes this source builds on every path through the function building them.

    A construction counts unless something between it and its enclosing
    function can skip it: a branch, a loop, an except clause, a
    comprehension, a conditional expression, a short-circuit or a lambda.
    """
    tree = ast.parse(source)
    parents = {child: node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    found: set[str] = set()
    for node in ast.walk(tree):
        if not (
            isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in known
        ):
            continue
        above = parents.get(node)
        skippable = False
        while above is not None and not isinstance(above, ast.FunctionDef | ast.AsyncFunctionDef):
            if isinstance(above, _CONDITIONAL):
                skippable = True
                break
            above = parents.get(above)
        if not skippable:
            found.add(node.func.id)
    return frozenset(found)


def _command_event(slice_dir: Path) -> str | None:
    """The one event class a slice's command names, or None when it names none.

    The sole class the slice builds or, among several, the sole one it
    builds on every path. The module docstring says why the second counts
    and why nothing else does.
    """
    emitted = _emitted_event_classes(slice_dir)
    if len(emitted) == 1:
        return next(iter(emitted))
    known = _event_class_names()
    always: set[str] = set()
    for path in sorted(tracked_python_files()):
        if path.is_relative_to(slice_dir):
            always |= _built_on_every_path(path.read_text(), known)
    return next(iter(always)) if len(always) == 1 else None


@cache
def _single_event_slices() -> dict[str, tuple[str, str]]:
    """Map bc/slice to its command class and the one event class that command names."""
    out: dict[str, tuple[str, str]] = {}
    for slice_dir in _command_slices():
        command = _command_class(slice_dir)
        event = _command_event(slice_dir)
        if command is None or event is None:
            continue
        out[_slice_key(slice_dir)] = (command, event)
    return out


def test_the_command_slice_scan_finds_at_least_one_single_event_slice() -> None:
    """Guard the enumeration: an empty parameter set skips, it does not fail."""
    assert _single_event_slices(), (
        "No slice resolves to a command class plus exactly one emitted event, so "
        "the derivation rule below ran against nothing."
    )


def test_the_scan_keeps_a_slice_that_emits_more_than_its_commands_event() -> None:
    """Guard the second branch the way the first is guarded.

    A slice that builds a second event class beside its own leaves the
    first branch, and if the second stopped matching, its parameter would
    vanish from the rule below and the count would be the only witness.
    """
    kept = [
        _slice_key(slice_dir)
        for slice_dir in _command_slices()
        if _slice_key(slice_dir) in _single_event_slices()
        and len(_emitted_event_classes(slice_dir)) > 1
    ]
    assert kept, (
        "No slice that builds more than one event class is in scope, so a slice "
        "emitting its own event and a conditional second one is not being checked."
    )


_SHAPES: dict[str, tuple[str, frozenset[str]]] = {
    "its-event-and-a-consequence": (
        "def decide():\n"
        "    events = [Opened()]\n"
        "    if more:\n"
        "        events.append(Noted())\n"
        "    return events\n",
        frozenset({"Opened"}),
    ),
    "a-pair-built-together": (
        "def decide():\n    return [Opened(), Noted()]\n",
        frozenset({"Opened", "Noted"}),
    ),
    "a-choice-between-two": (
        "def decide():\n"
        "    if more:\n"
        "        return [Opened()]\n"
        "    return [Noted()] if other else []\n",
        frozenset(),
    ),
}
"""The three shapes the scope section names, written small."""


@pytest.mark.parametrize("shape", sorted(_SHAPES))
def test_a_multi_event_shape_yields_only_the_classes_built_on_every_path(shape: str) -> None:
    """Only the first shape leaves one class, which is the one the rule then checks."""
    source, expected = _SHAPES[shape]
    assert _built_on_every_path(source, frozenset({"Opened", "Noted"})) == expected


def test_every_command_slice_resolves_a_command_class() -> None:
    unresolved = [_slice_key(d) for d in _command_slices() if _command_class(d) is None]
    assert not unresolved, (
        "These slices declare a command module but no class could be resolved by "
        f"any of the three documented strategies: {unresolved}. Name the class "
        "after the slice directory, or have the handler's command-label constant "
        "name it, or reduce the command module to a single class."
    )


@pytest.mark.parametrize(
    ("command", "event"),
    [
        ("RegisterActor", "ActorRegistered"),
        ("DeactivateActor", "ActorDeactivated"),
        ("RelocateAsset", "AssetRelocated"),
        ("StopRun", "RunStopped"),
        ("DenyRequest", "RequestDenied"),
        ("HoldProcedure", "ProcedureHeld"),
        ("AmendClearanceScope", "ClearanceScopeAmended"),
    ],
    ids=lambda pair: str(pair),
)
def test_a_well_formed_pair_derives(command: str, event: str) -> None:
    """The stemming rules, on pairs this repository does not have.

    Three of these spellings are the documented adjustments: silent-e
    restoration, consonant de-doubling, and terminal y to i. One is an
    irregular. The last carries two subject tokens, to show the rule
    keeps every token after the verb rather than just the first.
    """
    assert _derives(command, event)


@pytest.mark.parametrize(
    ("command", "event", "why"),
    [
        ("RegisterActor", "ActorCreated", "different verb"),
        ("RegisterActor", "RegisteredActor", "verb still leading, noun last"),
        ("AmendClearanceScope", "ScopeClearanceAmended", "subject tokens reordered"),
        ("AmendClearanceScope", "ClearanceAmended", "a subject token dropped"),
        ("RegisterActor", "ActorRegisteredTwice", "a token nobody asked for"),
    ],
    ids=lambda triple: str(triple),
)
def test_a_malformed_pair_does_not_derive(command: str, event: str, why: str) -> None:
    """The negative cases, which nothing in this repository supplies.

    Every command slice here derives cleanly, so the rule above passes
    whatever `_derives` returns: hardwired to True it would be dead and
    green. These are the pairs that must be refused, and the fourth is
    the one the rule exists for. R3 is noun-LAST and is the rule most
    often read backwards, so a comparison that accepted the tokens in
    any order would be blind to exactly the mistake it was written to
    catch. `RegisteredActor` is that mistake: every token is present
    and only its position is wrong.

    Tense is deliberately absent from this list. `ActorRegister` has its
    verb last and passes here; the past-tense rule next door is what
    refuses it.
    """
    assert not _derives(command, event), f"{command} -> {event} should be refused: {why}"


@pytest.mark.parametrize("key", sorted(_single_event_slices()))
def test_a_command_name_derives_the_event_it_emits(key: str) -> None:
    command, event = _single_event_slices()[key]
    assert _derives(command, event), (
        f"{key}: the command {command!r} does not derive the event {event!r}. Move "
        "the leading verb to the end, put it in the past participle, and keep "
        "every other token unchanged and in order. Rename one side to match the "
        "other; there is no allowlist, because a pair a reader cannot derive is "
        "the cost this rule exists to refuse."
    )
