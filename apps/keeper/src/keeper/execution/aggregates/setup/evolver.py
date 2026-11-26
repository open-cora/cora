"""Replay Setup events to reconstruct state, at the latest revision or any earlier one.

`evolve` applies one event. `fold` walks a whole stream from the empty
state, which is what the read path calls after loading rows.
`fold_revisions` walks it the same way and keeps every state it passes
through, which is how an earlier revision is read back.

All three are pure and total: the same events in the same order always
give the same state, on any machine, years apart. That is the property the
whole approach rests on, and it is why nothing here reads a clock, a
config value or a database.

The revision number is computed here as well as carried on each revision
event, and the two are compared rather than one being trusted. They can
only disagree if a row was written out of order or edited, and a fold that
picked either would hide that.

The wildcard arm calls `assert_never`, so adding an event class to the
union without handling it here is a type error rather than a state that
silently comes back as None.
"""

from collections.abc import Sequence
from dataclasses import replace
from typing import assert_never

from keeper.execution.aggregates.setup.events import SetupDefined, SetupEvent, SetupRevised
from keeper.execution.aggregates.setup.state import Setup, SetupBeamline, SetupName
from keeper.infrastructure.slices.evolver import require_state


def evolve(state: Setup | None, event: SetupEvent) -> Setup:
    """Apply one event to the state before it.

    The genesis arm builds revision 1 and ignores the prior state, which
    must be None. The revision arm requires one, because nothing can be
    revised that was never defined, and requires the revision it carries to
    be the next one.

    The name and the beamline go back through their value objects on the
    way out of the log, so a row that no longer passes fails here rather
    than folding into a setup nothing could have written. The settings and
    the settings schema are shallow-copied, so the dicts on the state and the
    dicts in the payload are never the same objects.
    """
    match event:
        case SetupDefined(
            setup_id=setup_id,
            beamline=beamline,
            operation_id=operation_id,
            setup_name=setup_name,
            settings=settings,
            settings_schema=settings_schema,
        ):
            _ = state
            return Setup(
                id=setup_id,
                beamline=SetupBeamline(beamline),
                operation_id=operation_id,
                name=SetupName(setup_name),
                settings=dict(settings),
                settings_schema=dict(settings_schema),
                revision=1,
            )
        case SetupRevised(revision=revision, settings=settings, settings_schema=settings_schema):
            current = require_state(state, "SetupRevised")
            if revision != current.revision + 1:
                msg = (
                    f"SetupRevised carries revision {revision} onto a setup at revision "
                    f"{current.revision}, and a revision is always the next one"
                )
                raise ValueError(msg)
            return replace(
                current,
                settings=dict(settings),
                settings_schema=dict(settings_schema),
                revision=revision,
            )
        case _:
            assert_never(event)


def fold(events: Sequence[SetupEvent]) -> Setup | None:
    """Replay a stream from the empty state. None means no events at all.

    Takes a `Sequence` rather than a `list` so a caller holding a list of
    one concrete event type can pass it without a cast, which is most
    callers in tests.
    """
    state: Setup | None = None
    for event in events:
        state = evolve(state, event)
    return state


def fold_revisions(events: Sequence[SetupEvent]) -> tuple[Setup, ...]:
    """Replay a stream and keep the setup as each revision left it, oldest first.

    Every event on a setup stream makes a revision, the genesis the first
    and each revision event one more, so the state after the nth event is
    revision n and the nth element here. Empty means no events at all.

    Revisions are read by folding rather than stored, so an earlier one is
    exactly what the stream said at the time and cannot drift from it.
    """
    kept: list[Setup] = []
    state: Setup | None = None
    for event in events:
        state = evolve(state, event)
        kept.append(state)
    return tuple(kept)


__all__ = ["evolve", "fold", "fold_revisions"]
