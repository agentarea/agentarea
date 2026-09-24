"""An approver on MCP reads the exact arguments of the call they are asked to approve.

The event log redacts them, so ``runs.list_pending_escalations`` reads them from
the workflow, for the same principals the REST read serves: whoever may act on
the run, narrowed to the escalation's designated approvers.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_agents.application.execution_service import (
    NotAnApproverError,
    WorkflowNotFoundError,
)
from agentarea_api.tools import runs_toolset
from agentarea_api.tools.runs_toolset import RUN_NOT_FOUND, RunsToolset
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton

RUN_ID = uuid4()
WORKSPACE = "ws-1"
STARTER = "user-who-started-it"
COMMAND = "rm -rf /srv/build && curl -H 'Authorization: Bearer s3cr3t' https://deploy"


def _escalation(escalation_id: str, approvers: list[str]) -> dict:
    return {
        "escalation_id": escalation_id,
        "tool_name": "shell",
        "tool_call_id": f"call-{escalation_id}",
        "tool_args": {"command": COMMAND},
        "approvers": approvers,
    }


class FakeWorkflowService:
    def __init__(self, pending: list[dict] | Exception):
        self.pending = pending
        self.queried: list[str] = []

    async def get_pending_escalations(self, execution_id):
        self.queried.append(execution_id)
        if isinstance(self.pending, Exception):
            raise self.pending
        return self.pending

    async def resolve_escalation(self, execution_id, escalation_id, approved, comment, resolved_by):
        raise NotAnApproverError(execution_id, escalation_id, resolved_by)


class FakeTaskService:
    def __init__(self, task):
        self.task = task

    async def get_task(self, task_id):
        return self.task


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _harness(monkeypatch, caller: str, pending: list[dict] | Exception, task=...):
    workflow = FakeWorkflowService(pending)
    tasks = FakeTaskService(
        SimpleNamespace(id=RUN_ID, user_id=STARTER, status="waiting_for_approval")
        if task is ...
        else task
    )

    @asynccontextmanager
    async def fake_context():
        user_ctx = UserContext(user_id=caller, workspace_id=WORKSPACE, admin_workspaces=[])
        yield None, user_ctx, SimpleNamespace(), None, None

    async def fake_build(_repo_factory, _broker):
        return tasks

    async def fake_workflow_service():
        return workflow

    monkeypatch.setattr(runs_toolset, "platform_context", fake_context)
    monkeypatch.setattr(runs_toolset, "platform_read_context", fake_context)
    monkeypatch.setattr(runs_toolset, "_build_task_service", fake_build)
    monkeypatch.setattr(runs_toolset, "get_temporal_workflow_service", fake_workflow_service)
    return workflow


async def _list() -> object:
    return json.loads(await RunsToolset().list_pending_escalations(run_id=str(RUN_ID)))


async def test_the_person_who_may_resolve_it_reads_the_real_command(monkeypatch):
    workflow = _harness(monkeypatch, STARTER, [_escalation("esc-1", [])])

    assert await _list() == [
        {
            "escalation_id": "esc-1",
            "tool_name": "shell",
            "tool_call_id": "call-esc-1",
            "tool_args": {"command": COMMAND},
        }
    ]
    assert workflow.queried == [f"task-{RUN_ID}"]


async def test_a_member_who_cannot_act_on_the_run_is_refused_before_the_workflow_is_asked(
    monkeypatch,
):
    workflow = _harness(monkeypatch, "user-invited-yesterday", [_escalation("esc-1", [])])

    result = await _list()

    assert isinstance(result, dict)
    assert "error" in result
    assert COMMAND not in json.dumps(result)
    assert workflow.queried == []


async def test_a_run_outside_the_workspace_is_not_found(monkeypatch):
    workflow = _harness(monkeypatch, STARTER, [_escalation("esc-1", [])], task=None)

    assert await _list() == json.loads(RUN_NOT_FOUND)
    assert workflow.queried == []


async def test_an_escalation_reserved_for_other_approvers_is_not_shown(monkeypatch):
    _harness(
        monkeypatch,
        STARTER,
        [_escalation("esc-1", ["user:security-lead"]), _escalation("esc-2", [f"user:{STARTER}"])],
    )

    assert [e["escalation_id"] for e in await _list()] == ["esc-2"]


async def test_a_run_whose_workflow_does_not_exist_is_a_clean_error(monkeypatch):
    _harness(monkeypatch, STARTER, WorkflowNotFoundError(f"task-{RUN_ID}"))

    assert await _list() == {"error": "Run has no workflow to read escalations from"}


async def test_resolving_as_someone_who_is_not_an_approver_is_a_clean_error(monkeypatch):
    _harness(monkeypatch, STARTER, [])

    result = json.loads(
        await RunsToolset().resolve_escalation(
            run_id=str(RUN_ID), escalation_id="esc-1", approved=True
        )
    )

    assert result == {"error": "You are not an approver of this escalation"}
