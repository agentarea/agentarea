"""``events/poll`` over the events read model: a page of one stream's events after a position.

The position is the read model's sequence. A page scans at most ``scan_limit``
rows, so a narrow filter over a busy stream still answers quickly; the cursor
then stands past what was scanned and ``has_more`` asks for the next page.
"""

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from ..domain.models import RecordedEvent
from ..infrastructure.event_repository import StreamEventRepository

SCAN_LIMIT = 1000
_CHUNK = 200


@dataclass(frozen=True)
class PollPage:
    events: list[RecordedEvent]
    #: The sequence of the last row scanned: everything up to it was answered or did not match.
    position: int
    has_more: bool


async def head_position(events: StreamEventRepository, stream_id: UUID) -> int:
    """The sequence of the stream's newest event in the read model; 0 when it has none."""
    newest = await events.read_before(stream_id, None, 1)
    return newest[0].sequence if newest else 0


async def read_page(
    events: StreamEventRepository,
    stream_id: UUID,
    *,
    after: int,
    since: datetime,
    admits: Callable[[RecordedEvent], bool],
    max_events: int,
    scan_limit: int = SCAN_LIMIT,
) -> PollPage:
    position = after
    collected: list[RecordedEvent] = []
    scanned = 0
    while scanned < scan_limit:
        limit = min(_CHUNK, scan_limit - scanned)
        rows = await events.read_since(stream_id, since, position, limit)
        for index, row in enumerate(rows):
            scanned += 1
            position = row.sequence
            if not admits(row):
                continue
            collected.append(row)
            if len(collected) == max_events:
                more = index < len(rows) - 1 or bool(
                    await events.read_since(stream_id, since, position, 1)
                )
                return PollPage(collected, position, more)
        if len(rows) < limit:
            return PollPage(collected, position, False)
    return PollPage(collected, position, True)
