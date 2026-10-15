from uuid import UUID, uuid4
from zlib import crc32

from agentarea_common.broker.topics import stream_events_partition
from agentarea_streams.domain.filters import EventFilter
from agentarea_streams.domain.keys import (
    MAX_EVENT_BYTES,
    derived_event_id,
    encoded_size,
    event_id_for,
    task_id_for,
)


def test_the_same_key_always_names_the_same_event():
    stream = uuid4()
    assert event_id_for(stream, "gh:1") == event_id_for(stream, "gh:1")
    assert event_id_for(stream, "gh:1") != event_id_for(uuid4(), "gh:1")
    assert isinstance(event_id_for(stream, "gh:1"), UUID)


def test_a_derived_event_is_named_by_its_processor_and_source_event():
    processor, source = uuid4(), uuid4()
    assert derived_event_id(processor, source) == derived_event_id(processor, source)
    assert derived_event_id(processor, source) != derived_event_id(uuid4(), source)
    assert derived_event_id(processor, source) != derived_event_id(processor, uuid4())


def test_task_id_is_stable_per_subscription_and_event():
    sub, event, other = uuid4(), uuid4(), uuid4()
    assert task_id_for(sub, event) == task_id_for(sub, event)
    assert task_id_for(sub, event) != task_id_for(sub, other)


def test_a_stream_is_carried_on_one_stable_partition():
    stream = UUID("00000000-0000-0000-0000-000000000001")
    assert stream_events_partition(stream, 16) == f"streams.events.{crc32(stream.bytes) % 16}"
    assert stream_events_partition(stream, 1) == "streams.events.0"


def test_size_is_measured_on_the_utf8_json():
    assert encoded_size({"a": "é"}) == len('{"a":"é"}'.encode())
    assert MAX_EVENT_BYTES == 256 * 1024


def test_empty_filter_matches_everything():
    assert EventFilter().matches("anything", {})


def test_kind_matches_exact_parent_and_child_like_the_webhook_event_filter():
    f = EventFilter(kinds=["pull_request"])
    assert f.matches("pull_request", {})
    assert f.matches("pull_request.opened", {})
    assert not f.matches("push", {})
    assert EventFilter(kinds=["pull_request.opened"]).matches("pull_request", {})


def test_fields_compare_dotted_paths_for_equality():
    f = EventFilter(fields={"raw_data.action": "opened"})
    assert f.matches("x", {"raw_data": {"action": "opened"}})
    assert not f.matches("x", {"raw_data": {"action": "closed"}})
    assert not f.matches("x", {})


def test_trigger_event_types_become_a_kind_filter():
    assert EventFilter.from_trigger_event_types(None) == EventFilter()
    assert EventFilter.from_trigger_event_types(["message"]).kinds == ["message"]


def test_a_body_field_reads_a_generic_webhook_s_raw_data():
    """A generic webhook stores its body once, as ``raw_data``; a filter
    written against the ``body`` copy it used to carry still matches."""
    f = EventFilter(fields={"body.type": "deployment"})
    assert f.matches("x", {"raw_data": {"type": "deployment"}})
    assert not f.matches("x", {"raw_data": {"type": "release"}})


def test_a_stored_event_with_its_own_body_is_read_as_stored():
    f = EventFilter(fields={"body.type": "deployment"})
    assert f.matches("x", {"body": {"type": "deployment"}, "raw_data": {"type": "other"}})
