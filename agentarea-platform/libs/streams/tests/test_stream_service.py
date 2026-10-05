from unittest.mock import MagicMock
from uuid import uuid4

import pytest
from agentarea_common.config.streams import EventStreamSettings
from agentarea_streams.application.stream_service import StreamService
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
