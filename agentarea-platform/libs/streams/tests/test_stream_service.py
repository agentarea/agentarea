from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.application.stream_service import StreamService, webhook_stream_name
from agentarea_streams.domain import EventFilter, ForwardLoopError


def _service() -> StreamService:
    factory = MagicMock()
    return StreamService(factory, EventStreamSettings())


async def test_a_forward_may_not_write_into_its_input():
    stream = uuid4()
    with pytest.raises(ForwardLoopError, match="its own input"):
        await _service().create_forward(
            stream_id=stream, output_stream_ids=[uuid4(), stream], event_filter=EventFilter()
        )


async def test_a_forward_needs_an_output():
    with pytest.raises(ForwardLoopError, match="at least one output"):
        await _service().create_forward(
            stream_id=uuid4(), output_stream_ids=[], event_filter=EventFilter()
        )


def test_a_short_name_and_webhook_id_are_combined_unchanged():
    assert webhook_stream_name("GitHub pushes", "wh123") == "GitHub pushes (wh123)"


def test_a_long_trigger_name_is_truncated_so_the_stream_name_still_fits():
    webhook_id = "w" * 200
    name = webhook_stream_name("n" * 300, webhook_id)
    assert len(name) <= 255
    assert name.endswith(f" ({webhook_id})")


def test_a_webhook_id_too_long_for_any_name_raises():
    webhook_id = "w" * 253
    with pytest.raises(ValueError, match="255"):
        webhook_stream_name("short name", webhook_id)
