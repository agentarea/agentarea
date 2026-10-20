"""Fixtures shared by the unit tests that drive workflow methods outside Temporal."""

import pytest
from agentarea_execution.workflows.agent.base import AgentWorkflowBase


@pytest.fixture(autouse=True)
def _cursor_window_path(monkeypatch):
    """Outside Temporal ``workflow.patched`` cannot run; these tests drive the run
    as histories recorded before the task log record did. The record path is
    covered end to end by the workflow integration tests."""
    monkeypatch.setattr(AgentWorkflowBase, "_task_log_on", lambda self: False)


@pytest.fixture(autouse=True)
def _session_decides_follow_up(monkeypatch):
    """Runs started after session-decides-follow-up-v1: the task's session decides the wait."""
    monkeypatch.setattr(AgentWorkflowBase, "_session_decides_follow_up", lambda self: True)
