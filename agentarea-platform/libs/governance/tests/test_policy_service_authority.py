"""Writing a governance rule takes workspace-admin authority, whoever calls.

``DELETE /v1/policies/{id}`` required an admin; ``policies_delete`` over MCP
reached the same ``GovernancePolicyService.delete_rule`` with nothing in the
way, so any member could drop a deny rule or lift their own spend cap by asking
an agent to. The check now lives in the service, so the router, the toolset and
the bundle installer all inherit it.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from agentarea_governance.application.service import GovernancePolicyService
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from fastapi import HTTPException

WORKSPACE = "ws-acme"


class _Rules:
    def __init__(self):
        self.calls: list[str] = []

    async def create(self, rule):
        self.calls.append("create")
        return rule

    async def update(self, rule_id, **fields):
        self.calls.append("update")

    async def set_enabled(self, rule_id, enabled):
        self.calls.append("set_enabled")

    async def delete(self, rule_id):
        self.calls.append("delete")
        return True


def _service(user_context: UserContext) -> tuple[GovernancePolicyService, _Rules]:
    rules = _Rules()
    factory = SimpleNamespace(
        session=AsyncMock(),
        user_context=user_context,
        create_repository=lambda _cls: rules,
    )
    return GovernancePolicyService(factory), rules


def _rule() -> PolicyRule:
    return PolicyRule(
        subject_type=PolicySubjectType.WORKSPACE,
        subject_id=WORKSPACE,
        target="tool:shell",
        effect=PolicyEffect.DENY,
    )


@pytest.fixture(autouse=True)
def _authorization():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


WRITES = {
    "create_rule": lambda s: s.create_rule(rule=_rule(), subject_id=WORKSPACE),
    "update_rule": lambda s: s.update_rule(rule_id="r-1", enabled=False),
    "set_rule_enabled": lambda s: s.set_rule_enabled(rule_id="r-1", enabled=False),
    "delete_rule": lambda s: s.delete_rule(rule_id="r-1"),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("write", WRITES.values(), ids=WRITES.keys())
async def test_a_member_cannot_write_a_rule(write) -> None:
    member = UserContext(user_id="user-member", workspace_id=WORKSPACE, admin_workspaces=[])
    service, rules = _service(member)

    with pytest.raises(HTTPException) as refused:
        await write(service)

    assert refused.value.status_code == 403
    assert rules.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("write", WRITES.values(), ids=WRITES.keys())
async def test_an_admin_writes_the_rule(write) -> None:
    admin = UserContext(user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])
    service, rules = _service(admin)

    await write(service)

    assert len(rules.calls) == 1
