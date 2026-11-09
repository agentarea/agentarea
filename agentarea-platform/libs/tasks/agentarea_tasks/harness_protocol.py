"""The frames a runner and the platform exchange over the runner's socket (ADR-0051).

Up, from the runner: ``hello`` once, ``ping`` while it is connected, and per
turn ``turn.started``, ``turn.event``, ``approval.request``, ``steer.accepted``,
``steer.rejected`` and ``turn.finished``. Down, to the runner: ``welcome``,
``turn.assign``, ``turn.steer``, ``turn.cancel`` and ``approval.decision``.

A ``turn.event`` carries the turn's own position ``seq``, which the task's
workflow uses to drop a replay. Text deltas and command output are broadcast
only, never kept.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field, TypeAdapter

# A runner pings this often; a running turn's token lapses LEASE_SECONDS after its last renewal.
PING_SECONDS = 10
LEASE_SECONDS = 30
# At most one text snapshot and one output snapshot per this many seconds per item.
SNAPSHOT_INTERVAL_SECONDS = 0.1
PROGRESS_INTERVAL_SECONDS = 0.5
# The tail of a command's output a progress snapshot carries.
PROGRESS_TAIL_CHARS = 4000


class ReportedModel(BaseModel):
    name: str
    reasoning_levels: list[str] = Field(default_factory=list)
    default_reasoning: str | None = None


class Hello(BaseModel):
    type: Literal["hello"]
    models: list[ReportedModel] | None = None
    default_model: str | None = None
    # Turns the runner runs at once.
    capacity: int = Field(1, ge=1, le=16)
    version: str | None = None
    # Turns still running in this runner from before it reconnected; none is kept.
    turns: list[UUID] = Field(default_factory=list)


class Ping(BaseModel):
    type: Literal["ping"]


class TurnStarted(BaseModel):
    """The CLI's session of the turn is known: a follow-up or a rerun resumes it."""

    type: Literal["turn.started"]
    turn_id: UUID
    session_id: str


class MessageDelta(BaseModel):
    kind: Literal["message.delta"]
    item_id: str
    text: str
    channel: Literal["text", "thinking"] = "text"


class Message(BaseModel):
    kind: Literal["message"]
    item_id: str
    text: str
    model: str | None = None


class ToolCall(BaseModel):
    kind: Literal["tool.call"]
    id: str
    name: str
    arguments: dict[str, Any] = Field(default_factory=dict)


class ToolProgress(BaseModel):
    kind: Literal["tool.progress"]
    id: str
    name: str
    output: str


class ToolResult(BaseModel):
    kind: Literal["tool.result"]
    id: str
    name: str
    output: str = ""
    success: bool = True
    exit_code: int | None = None


TurnEventBody = Annotated[
    MessageDelta | Message | ToolCall | ToolProgress | ToolResult, Field(discriminator="kind")
]
LIVE_KINDS = frozenset({"message.delta", "tool.progress"})


class TurnEvent(BaseModel):
    type: Literal["turn.event"]
    turn_id: UUID
    seq: int = Field(ge=1)
    event: TurnEventBody


class ApprovalRequest(BaseModel):
    """The CLI waits for a person to allow a command, a file change or a tool call."""

    type: Literal["approval.request"]
    turn_id: UUID
    request_id: str
    # The CLI's item the request is about: the command or the file change.
    item_id: str | None = None
    kind: Literal["command", "file_change", "tool"]
    tool_name: str
    arguments: dict[str, Any] = Field(default_factory=dict)
    reason: str | None = None


class SteerAccepted(BaseModel):
    """A message sent into a running turn reached the CLI."""

    type: Literal["steer.accepted"]
    turn_id: UUID
    message_id: str


class SteerRejected(BaseModel):
    """A message sent into a turn found it already over; it becomes the next turn."""

    type: Literal["steer.rejected"]
    turn_id: UUID
    message_id: str


class TurnFinished(BaseModel):
    type: Literal["turn.finished"]
    turn_id: UUID
    status: Literal["completed", "failed", "interrupted"]
    response: str | None = None
    error: str | None = None
    session_id: str | None = None


UpFrame = Annotated[
    Hello
    | Ping
    | TurnStarted
    | TurnEvent
    | ApprovalRequest
    | SteerAccepted
    | SteerRejected
    | TurnFinished,
    Field(discriminator="type"),
]
UP_FRAME: TypeAdapter[UpFrame] = TypeAdapter(UpFrame)


class ProtocolError(Exception):
    """A frame that is valid alone but not where the runner sent it."""


def parse_up_frame(raw: str) -> UpFrame:
    """A frame from the runner; raises ``pydantic.ValidationError`` for anything else."""
    return UP_FRAME.validate_json(raw)


class LiveSnapshots:
    """What a turn's live deltas add up to, and when each item may be broadcast again.

    A text snapshot carries the item's whole reply so far, as the platform's
    own loop streams it; a progress snapshot carries the tail of a command's
    output. Both are throttled per item; the completed item supersedes them.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._text: dict[str, str] = {}
        self._thinking: dict[str, str] = {}
        self._output: dict[str, str] = {}
        self._sent: dict[tuple[str, str], float] = {}

    def text(self, item_id: str, delta: str, channel: str) -> tuple[str, str] | None:
        """``(text, thinking)`` so far when the item is due a snapshot, else None."""
        store = self._thinking if channel == "thinking" else self._text
        store[item_id] = store.get(item_id, "") + delta
        if not self._due(("text", item_id), SNAPSHOT_INTERVAL_SECONDS):
            return None
        return self._text.get(item_id, ""), self._thinking.get(item_id, "")

    def output(self, call_id: str, delta: str) -> str | None:
        """The tail of the call's output so far when it is due a snapshot, else None."""
        self._output[call_id] = (self._output.get(call_id, "") + delta)[-PROGRESS_TAIL_CHARS:]
        if not self._due(("output", call_id), PROGRESS_INTERVAL_SECONDS):
            return None
        return self._output[call_id]

    def forget(self, item_id: str) -> None:
        for store in (self._text, self._thinking, self._output):
            store.pop(item_id, None)
        self._sent.pop(("text", item_id), None)
        self._sent.pop(("output", item_id), None)

    def _due(self, key: tuple[str, str], interval: float) -> bool:
        now = self._clock()
        last = self._sent.get(key)
        if last is not None and now - last < interval:
            return False
        self._sent[key] = now
        return True
