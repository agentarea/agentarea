"""Task rows and workflow events as the A2A wire sees them."""

import logging
from uuid import uuid4

import pytest
from a2a.types import Role, TaskArtifactUpdateEvent, TaskState, TaskStatusUpdateEvent
from agentarea_api.api.v1.a2a_mapping import task_state, to_a2a_task, workflow_event_to_a2a
from agentarea_common.events.contract import LLM_CHUNK, TASK_COMPLETED, TASK_FAILED
from agentarea_tasks.domain.models import AgentTask


def _task(**fields) -> AgentTask:
    return AgentTask(
        id=uuid4(),
        title="t",
        description="d",
        query="q",
        user_id="u",
        workspace_id="ws",
        agent_id=uuid4(),
        **fields,
    )


@pytest.mark.parametrize(
    ("status", "state"),
    [
        ("scheduled", TaskState.TASK_STATE_SUBMITTED),
        ("running", TaskState.TASK_STATE_WORKING),
        ("waiting_for_input", TaskState.TASK_STATE_INPUT_REQUIRED),
        ("waiting_for_approval", TaskState.TASK_STATE_INPUT_REQUIRED),
        ("blocked", TaskState.TASK_STATE_FAILED),
        ("cancelled", TaskState.TASK_STATE_CANCELED),
    ],
)
def test_every_row_status_has_a_task_state(status, state):
    assert task_state(status) == state


def test_unknown_status_reads_as_unspecified_and_is_reported(caplog):
    with caplog.at_level(logging.WARNING):
        assert task_state("half-baked") == TaskState.TASK_STATE_UNSPECIFIED
    assert "half-baked" in caplog.text


def test_failed_task_carries_its_error_as_the_status_message():
    wire = to_a2a_task(_task(status="failed", error_message="model quota exhausted"))

    assert wire.status.state == TaskState.TASK_STATE_FAILED
    assert wire.status.message.role == Role.ROLE_AGENT
    assert wire.status.message.parts[0].text == "model quota exhausted"
    assert list(wire.artifacts) == []


def test_context_id_is_the_one_the_client_sent():
    wire = to_a2a_task(_task(status="submitted", metadata={"a2a_context_id": "ctx-1"}))

    assert wire.context_id == "ctx-1"


def test_failed_event_ends_the_stream_without_an_artifact():
    events, terminal = workflow_event_to_a2a(
        TASK_FAILED, {"error": "boom"}, task_id="t", context_id="c"
    )

    assert terminal
    [status] = events
    assert isinstance(status, TaskStatusUpdateEvent)
    assert status.status.state == TaskState.TASK_STATE_FAILED


def test_completed_event_without_text_sends_only_the_status():
    events, terminal = workflow_event_to_a2a(TASK_COMPLETED, {}, task_id="t", context_id="c")

    assert terminal
    assert [type(e) for e in events] == [TaskStatusUpdateEvent]


def test_empty_chunk_emits_nothing():
    assert workflow_event_to_a2a(LLM_CHUNK, {"chunk": ""}, task_id="t", context_id="c") == (
        [],
        False,
    )


def test_chunk_appends_to_the_response_artifact():
    [event], terminal = workflow_event_to_a2a(
        LLM_CHUNK, {"chunk": "hel"}, task_id="t", context_id="c"
    )

    assert not terminal
    assert isinstance(event, TaskArtifactUpdateEvent)
    assert (event.append, event.last_chunk, event.artifact.artifact_id) == (True, False, "t")
