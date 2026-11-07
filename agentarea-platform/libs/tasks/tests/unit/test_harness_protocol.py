"""The runner socket's frames: what is accepted, and what is broadcast when."""

import pytest
from agentarea_tasks.harness_protocol import (
    Hello,
    LiveSnapshots,
    MessageDelta,
    SteerAccepted,
    SteerRejected,
    TurnEvent,
    parse_up_frame,
)
from pydantic import ValidationError

TURN = "6f1c1b2a-3d4e-4f50-8a9b-0c1d2e3f4a5b"


def test_frames_parse_by_type_and_turn_events_by_kind():
    hello = parse_up_frame('{"type": "hello", "capacity": 2, "turns": ["' + TURN + '"]}')
    assert isinstance(hello, Hello)
    assert hello.capacity == 2
    assert len(hello.turns) == 1

    event = parse_up_frame(
        '{"type": "turn.event", "turn_id": "' + TURN + '", "seq": 3,'
        ' "event": {"kind": "message.delta", "item_id": "msg_1", "text": "Hel"}}'
    )
    assert isinstance(event, TurnEvent)
    assert isinstance(event.event, MessageDelta)


@pytest.mark.parametrize(
    "raw",
    [
        '{"type": "claim"}',
        '{"type": "turn.event", "turn_id": "' + TURN + '", "seq": 0,'
        ' "event": {"kind": "message", "item_id": "m", "text": "x"}}',
        '{"type": "turn.event", "turn_id": "' + TURN + '", "seq": 1, "event": {"kind": "nope"}}',
        '{"type": "turn.finished", "turn_id": "' + TURN + '", "status": "stopped"}',
        '{"type": "hello", "capacity": 0}',
    ],
)
def test_anything_else_is_refused(raw):
    with pytest.raises(ValidationError):
        parse_up_frame(raw)


def test_steer_outcomes_name_the_message_they_answer():
    accepted = parse_up_frame(
        '{"type": "steer.accepted", "turn_id": "' + TURN + '", "message_id": "m1"}'
    )
    rejected = parse_up_frame(
        '{"type": "steer.rejected", "turn_id": "' + TURN + '", "message_id": "m2"}'
    )
    assert isinstance(accepted, SteerAccepted)
    assert accepted.message_id == "m1"
    assert isinstance(rejected, SteerRejected)
    assert rejected.message_id == "m2"


def test_text_snapshots_carry_the_reply_so_far_at_most_once_per_interval():
    now = [0.0]
    live = LiveSnapshots(clock=lambda: now[0])
    assert live.text("m", "Hel", "text") == ("Hel", "")
    assert live.text("m", "lo", "text") is None
    now[0] = 0.2
    assert live.text("m", "!", "text") == ("Hello!", "")
    assert live.text("other", "Hi", "text") == ("Hi", "")


def test_output_snapshots_keep_the_tail_and_forget_clears_the_item():
    now = [0.0]
    live = LiveSnapshots(clock=lambda: now[0])
    assert live.output("c", "x" * 5000) == "x" * 4000
    live.forget("c")
    assert live.output("c", "y") == "y"
