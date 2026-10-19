"""The events-view group dead-letters a message that is no stream event at once."""

import pytest
from agentarea_common.events.ports import IntegrationEvent, UnprocessableEventError
from agentarea_streams.application.events_view import EventsView


async def test_a_message_that_is_no_stream_event_is_unprocessable():
    view = EventsView(session_factory=None)  # type: ignore[arg-type]
    with pytest.raises(UnprocessableEventError):
        await view.handle(IntegrationEvent(type="lv.malformed", source="/test", data={}))
