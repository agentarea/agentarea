"""What started a trigger's run, told to the agent the same way for every source.

One block, rendered from the event alone: which trigger, which stream, the
event's kind, key, time and sequence, then its data. Nothing here knows a
provider; the data is the journaled (already scrubbed) payload, quoted as JSON
when small and handed over as a task input file when not. It is never cut.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from agentarea_common.trigger_event_file import (
    event_data_json,
    trigger_event_file_name,
    trigger_event_file_path,
)
from agentarea_streams.domain import JournaledEvent
from pydantic import BaseModel

# Above this many UTF-8 bytes of JSON the data goes to a file instead of the
# message. The message is also the run's goal, which the system prompt repeats.
EVENT_INLINE_LIMIT_BYTES = 16 * 1024


class TriggerEvent(BaseModel):
    """The event a trigger fired on, as far as its source knows it."""

    kind: str | None = None
    key: str | None = None
    received_at: datetime
    stream_name: str | None = None
    sequence: int | None = None
    data: dict[str, Any]

    @classmethod
    def from_journaled(cls, event: JournaledEvent, *, stream_name: str) -> "TriggerEvent":
        return cls(
            kind=event.type,
            key=event.event_key,
            received_at=event.received_at,
            stream_name=stream_name,
            sequence=event.sequence,
            data=event.data,
        )

    @classmethod
    def from_trigger_data(
        cls, trigger_data: dict[str, Any], *, received_at: datetime
    ) -> "TriggerEvent | None":
        """The events a channel, a poller or a replay handed over; None when there are none."""
        if not (trigger_data.get("events") or trigger_data.get("extracted_events")):
            return None
        return cls(received_at=received_at, data=trigger_data)


@dataclass(frozen=True)
class EventBlock:
    text: str
    # Set when the data did not fit inline: the task input file that must hold it.
    event_file: str | None = None


def _utc_iso(moment: datetime) -> str:
    aware = moment.replace(tzinfo=UTC) if moment.tzinfo is None else moment.astimezone(UTC)
    return aware.isoformat()


def render_event_block(
    *,
    trigger_name: str,
    trigger_type: str,
    event: TriggerEvent,
    inline_limit_bytes: int = EVENT_INLINE_LIMIT_BYTES,
) -> EventBlock:
    lines = ["## What started this run", f"- Trigger: {trigger_name} ({trigger_type})"]
    if event.stream_name is not None:
        lines.append(f"- Stream: {event.stream_name}")
    if event.kind is not None:
        lines.append(f"- Event kind: {event.kind}")
    if event.key is not None:
        lines.append(f"- Event key: {event.key}")
    lines.append(f"- Received: {_utc_iso(event.received_at)}")
    if event.sequence is not None:
        lines.append(f"- Stream sequence: {event.sequence}")

    data = event_data_json(event.data)
    size = len(data.encode())
    if size <= inline_limit_bytes:
        lines += ["", "Event data:", "```json", data, "```"]
        return EventBlock(text="\n".join(lines))

    file_name = trigger_event_file_name(event.sequence)
    lines += [
        "",
        f"Event data: {size} bytes of JSON, too large to quote here. The complete data is in "
        f"the task input file `{trigger_event_file_path(file_name)}`; read it from there.",
    ]
    return EventBlock(text="\n".join(lines), event_file=file_name)
