"""EventPublisher port: deliver newly appended events to downstream subscribers.

Durability model: read this before building a subscriber
---------------------------------------------------------

The events table itself is the durable record. Subscribers MUST poll
from a persisted watermark (`last_processed_position` per projection
or saga) by querying `events WHERE position > last_processed_position
ORDER BY position`. This is the only delivery channel that survives a
subscriber restart, a missed notification, or a publisher process
failure.

When you implement that polling loop, also handle the bigserial
sequence-rollback hazard documented at the top of
`aroc/infrastructure/ports/event_store.py`: a slow transaction can
commit AFTER a faster one with a higher position, and naive
`WHERE position > watermark` polling will silently skip it. Mitigations
listed there: track in-flight xmin via `pg_snapshot_xmin`, or re-scan
a small overlap window each tick.

`pg_notify` (fired by the AFTER INSERT trigger on `events`; see the
baseline migration) is a best-effort,
NON-DURABLE wake-up signal layered on top: it lets the subscriber
react with low latency without polling on a tight interval. If the
notification is dropped (subscriber not connected at commit time,
notify-payload deduplication on the server, transaction rollback
between commit and notify), the next poll cycle still picks the event
up via the watermark. NEVER use the notify payload as the actual
event delivery path, its content can be lost.

This port is the seam where richer publication mechanisms can land
later: NATS JetStream when cross-process
workers, durable replay outside main DB retention, or multi-region
federation arise. Whatever the adapter, the contract is the same: it
must guarantee at-least-once delivery to subscribers, and subscribers
must remain idempotent under that guarantee. The `event_id` UNIQUE
constraint on `events` (added in migration
the baseline migration) is the canonical dedup key.

Routing-key convention
----------------------

When a subscriber filters events to specific kinds, route on
`(stream_type, event_type)`: never on `event_type` alone. Today no
two BCs emit the same `event_type` discriminator, but `event_type` is
the unqualified class name (`"ActorRegistered"`, etc.) and a future
collision between BCs is plausible without this rule. Keying on the
pair pre-empts that whole class of silent-misroute bug.
"""

from collections.abc import Sequence
from typing import Protocol

from aroc.infrastructure.ports.event_store import StoredEvent


class EventPublisher(Protocol):
    """Deliver newly persisted events to downstream subscribers.

    Implementations vary in delivery semantics (in-process pg_notify
    wake-up + watermark polling today; NATS JetStream or similar
    later) but share the same at-least-once contract: subscribers may
    see the same `StoredEvent.event_id` more than once and must
    deduplicate idempotently.
    """

    async def publish(self, events: Sequence[StoredEvent]) -> None: ...
