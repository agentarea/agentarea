"""Tests for ContinueAsNewState model and serialization."""

from decimal import Decimal

import pytest

from agentarea_execution.workflows.models import (
    AgentGoal,
    ContinueAsNewState,
)


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
