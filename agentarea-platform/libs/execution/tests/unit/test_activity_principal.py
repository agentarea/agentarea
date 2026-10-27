"""Every activity of a run acts as the run's agent."""

import pytest
from agentarea_common.auth.context import Subject
from agentarea_execution.activities.dependencies import create_user_context


def test_an_activity_acts_as_the_runs_agent():
    context = create_user_context({"user_id": "alice", "workspace_id": "ws-1", "agent_id": "a-7"})

    assert context.subject == Subject(kind="agent", id="a-7")
    assert context.graph_subject == "Agent:a-7"
    # The person stays as attribution: who the run is for, not what it may reach.
    assert context.user_id == "alice"


def test_a_run_without_its_agent_is_a_wiring_bug():
    with pytest.raises(ValueError, match="agent_id"):
        create_user_context({"user_id": "alice", "workspace_id": "ws-1"})
