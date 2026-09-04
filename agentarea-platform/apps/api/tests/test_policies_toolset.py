"""Unit tests for the governance policies toolset.

The write path must run ``assert_enforceable`` exactly like the REST router:
the compiler debug-skips unenforceable rules, so a tool that accepted one would
report success for a rule that never takes effect — a fail-open with a green
tool result on top of it.
"""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_api.tools import policies_toolset
from agentarea_api.tools.policies_toolset import PoliciesToolset
from agentarea_governance.domain.rules import PolicyRule

RULE_ID = uuid4()
AGENT_ID = uuid4()


def _rule(**overrides) -> PolicyRule:
    fields = {
        "id": str(RULE_ID),
        "subject_type": "agent",
        "subject_id": "agent-1",
        "target": "tool:shell",
        "effect": "deny",
        "params": {},
        "enabled": True,
        "priority": 0,
    }
    fields.update(overrides)
    return PolicyRule(**fields)


class FakePolicyService:
    def __init__(self):
        self.created: list = []
        self.list_filters: dict | None = None
        self.rule: PolicyRule | None = _rule()
        self.deleted = True

    async def list_rules(self, **filters):
        self.list_filters = filters
        return [_rule()]

    async def get_rule(self, *, rule_id):
        return self.rule

    async def create_rule(self, *, rule, subject_id):
        self.created.append((rule, subject_id))
        return rule

    async def update_rule(self, *, rule_id, **fields):
        return _rule(**fields)

    async def delete_rule(self, *, rule_id):
        return self.deleted


class FakeResolver:
    def __init__(self):
        self.calls: list = []

    async def resolve(self, *, workspace_id, agent_id, task_policy):
        self.calls.append((workspace_id, agent_id, task_policy))
        return SimpleNamespace(model_dump=lambda: {"budget": {"run_budget_usd": "5.00"}})


@pytest.fixture
def harness(monkeypatch):
    service = FakePolicyService()
    resolver = FakeResolver()

    @asynccontextmanager
    async def fake_context():
        user_ctx = SimpleNamespace(user_id="user-1", workspace_id="ws-1")
        yield SimpleNamespace(), user_ctx, SimpleNamespace(), None, None

    monkeypatch.setattr(policies_toolset, "platform_context", fake_context)
    monkeypatch.setattr(policies_toolset, "platform_read_context", fake_context)
    monkeypatch.setattr(policies_toolset, "_build_service", lambda _repo: service)
    monkeypatch.setattr(policies_toolset, "_build_resolver", lambda _repo: resolver)
    return SimpleNamespace(service=service, resolver=resolver)


async def test_list_forwards_filters(harness):
    result = json.loads(await PoliciesToolset().list(subject_type="agent", enabled=True))

    assert harness.service.list_filters == {
        "subject_type": "agent",
        "subject_id": None,
        "effect": None,
        "target": None,
        "enabled": True,
    }
    assert result[0]["target"] == "tool:shell"


async def test_create_writes_an_enforceable_rule(harness):
    result = json.loads(
        await PoliciesToolset().create(
            subject_type="agent",
            subject_id="agent-1",
            target="tool:shell",
            effect="deny",
        )
    )

    assert result["effect"] == "deny"
    written, subject_id = harness.service.created[0]
    assert written.target == "tool:shell"
    assert subject_id == "agent-1"


async def test_create_refuses_a_rule_the_engine_would_ignore(harness):
    result = json.loads(
        await PoliciesToolset().create(
            subject_type="group",
            subject_id="group-1",
            target="tool:shell",
            effect="deny",
        )
    )

    assert "error" in result
    assert harness.service.created == []


async def test_update_refuses_an_unenforceable_patch(harness):
    result = json.loads(
        await PoliciesToolset().update(rule_id=str(RULE_ID), condition="user.team == 'ops'")
    )

    assert "error" in result


async def test_update_reports_a_missing_rule(harness):
    harness.service.rule = None

    result = json.loads(await PoliciesToolset().update(rule_id=str(RULE_ID), enabled=False))

    assert result == {"error": "Policy rule not found"}


async def test_delete_reports_a_missing_rule(harness):
    harness.service.deleted = False

    result = json.loads(await PoliciesToolset().delete(rule_id=str(RULE_ID)))

    assert result == {"error": "Policy rule not found"}


async def test_preview_resolves_for_the_callers_workspace(harness):
    result = json.loads(await PoliciesToolset().preview_effective_policy(agent_id=str(AGENT_ID)))

    assert result["budget"]["run_budget_usd"] == "5.00"
    workspace_id, agent_id, task_policy = harness.resolver.calls[0]
    assert workspace_id == "ws-1"
    assert agent_id == AGENT_ID
    assert task_policy is None
