from uuid import UUID, uuid4

from agentarea_streams.domain.filters import EventFilter
from agentarea_streams.domain.keys import (
    MAX_EVENT_BYTES,
    encoded_size,
    event_id_for,
    forward_event_key,
    task_id_for,
)


def test_the_same_key_always_names_the_same_event():
    stream = uuid4()
    assert event_id_for(stream, "gh:1") == event_id_for(stream, "gh:1")
    assert event_id_for(stream, "gh:1") != event_id_for(uuid4(), "gh:1")
    assert isinstance(event_id_for(stream, "gh:1"), UUID)


def test_forward_key_is_source_stream_and_sequence():
    src = UUID("00000000-0000-0000-0000-000000000001")
    assert forward_event_key(src, 42) == "00000000-0000-0000-0000-000000000001:42"


def test_task_id_is_stable_per_subscription_and_event():
    sub = uuid4()
    assert task_id_for(sub, 7) == task_id_for(sub, 7)
    assert task_id_for(sub, 7) != task_id_for(sub, 8)


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
