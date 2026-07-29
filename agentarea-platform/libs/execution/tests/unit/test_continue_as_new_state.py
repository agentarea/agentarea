"""Tests for ContinueAsNewState model and serialization."""

from decimal import Decimal

import pytest
from agentarea_execution.workflows.models import AgentGoal, ContinueAsNewState


class TestContinueAsNewState:
    """Test ContinueAsNewState model serialization and field handling."""

    @pytest.fixture
    def sample_goal(self):
        return AgentGoal(
            id="goal-1",
            description="Test goal",
            success_criteria=["Done"],
            max_iterations=10,
            requires_human_approval=False,
            context={},
        )

    @pytest.fixture
    def sample_state(self, sample_goal):
        return ContinueAsNewState(
            execution_id="exec-1",
            agent_id="agent-1",
            task_id="task-1",
            user_id="user-1",
            workspace_id="ws-1",
            goal=sample_goal,
            messages=[
                {"role": "system", "content": "You are helpful."},
                {"role": "user", "content": "Hello"},
            ],
            agent_config={"model_id": "gpt-4"},
            available_tools=[{"type": "function", "function": {"name": "search"}}],
            current_iteration=5,
            total_cost=0.05,
            budget_usd=10.0,
            context_window=128000,
            user_context_data={"key": "val"},
            continued_from_run_id="run-abc",
            agent_tool_registry={
                "delegate_to_researcher": {
                    "agent_id": "agent-2",
                    "agent_name": "researcher",
                },
            },
        )

    def test_roundtrip_serialization(self, sample_state):
        """State should survive model_dump -> ContinueAsNewState(**dict) roundtrip."""
        data = sample_state.model_dump()
        restored = ContinueAsNewState(**data)

        assert restored.execution_id == sample_state.execution_id
        assert restored.current_iteration == 5
        assert restored.total_cost == Decimal("0.05")
        assert len(restored.messages) == 2
        assert restored.goal.description == "Test goal"

    def test_agent_tool_registry_persisted(self, sample_state):
        """agent_tool_registry should survive serialization."""
        data = sample_state.model_dump()
        restored = ContinueAsNewState(**data)

        assert "delegate_to_researcher" in restored.agent_tool_registry
        entry = restored.agent_tool_registry["delegate_to_researcher"]
        assert entry["agent_id"] == "agent-2"
        assert entry["agent_name"] == "researcher"

    def test_empty_agent_tool_registry_default(self, sample_goal):
        """Empty agent_tool_registry should default to empty dict."""
        state = ContinueAsNewState(
            execution_id="exec-1",
            agent_id="agent-1",
            task_id="task-1",
            user_id="user-1",
            workspace_id="ws-1",
            goal=sample_goal,
            messages=[],
            agent_config={},
            available_tools=[],
            current_iteration=0,
            total_cost=0.0,
        )
        assert state.agent_tool_registry == {}

    def test_continued_from_run_id_optional(self, sample_goal):
        """continued_from_run_id should default to None."""
        state = ContinueAsNewState(
            execution_id="exec-1",
            agent_id="agent-1",
            task_id="task-1",
            user_id="user-1",
            workspace_id="ws-1",
            goal=sample_goal,
            messages=[],
            agent_config={},
            available_tools=[],
            current_iteration=0,
            total_cost=0.0,
        )
        assert state.continued_from_run_id is None

    def test_messages_preserved_as_dicts(self, sample_state):
        """Messages should be stored as dicts, not Message objects."""
        data = sample_state.model_dump()
        assert isinstance(data["messages"][0], dict)
        assert data["messages"][0]["role"] == "system"

    def test_pending_queues_default_empty(self, sample_state):
        """Queue fields default to empty so old payloads keep deserializing."""
        data = sample_state.model_dump()
        restored = ContinueAsNewState(**data)

        assert restored.message_queue == []
        assert restored.pending_escalations == {}
        assert restored.pending_input_requests == {}
        assert restored.a2ui_action_queue == []
        assert restored.awaiting_input is False
        assert restored.paused is False
        assert restored.workflow_metadata == {}

    def test_pending_queues_roundtrip(self, sample_goal):
        """Undrained queues and HITL state must survive continue-as-new."""
        from agentarea_execution.workflows.models import PendingEscalation

        state = ContinueAsNewState(
            execution_id="exec-1",
            agent_id="agent-1",
            task_id="task-1",
            user_id="user-1",
            workspace_id="ws-1",
            goal=sample_goal,
            messages=[],
            agent_config={},
            available_tools=[],
            current_iteration=3,
            total_cost=0.0,
            message_queue=[{"id": "m1", "content": "queued reply"}],
            pending_escalations={
                "esc-1": PendingEscalation(
                    escalation_id="esc-1",
                    tool_call_id="call-1",
                    tool_name="dangerous_tool",
                    resolved=True,
                    approved=True,
                )
            },
            pending_input_requests={
                "inp-1": {"resolved": True, "submission": {"answers": {"a": "b"}}, "questions": []}
            },
            a2ui_action_queue=[{"name": "click", "surface_id": "s1"}],
            awaiting_input=True,
            paused=True,
            pause_reason="user pause",
            workflow_metadata={
                "source": "agent_delegation",
                "workspace_manifest_ref": {"generation": 7, "manifest_sha256": "abc"},
            },
            validation_state="failed",
            validation_repair_attempts=1,
        )

        restored = ContinueAsNewState(**state.model_dump())

        assert restored.message_queue == [{"id": "m1", "content": "queued reply"}]
        assert restored.pending_escalations["esc-1"].approved is True
        assert restored.pending_escalations["esc-1"].tool_name == "dangerous_tool"
        assert restored.pending_input_requests["inp-1"]["submission"] == {"answers": {"a": "b"}}
        assert restored.a2ui_action_queue == [{"name": "click", "surface_id": "s1"}]
        assert restored.awaiting_input is True
        assert restored.paused is True
        assert restored.pause_reason == "user pause"
        assert restored.workflow_metadata == {
            "source": "agent_delegation",
            "workspace_manifest_ref": {"generation": 7, "manifest_sha256": "abc"},
        }
        assert restored.validation_state == "failed"
        assert restored.validation_repair_attempts == 1
        assert restored.validation_terminal is False
