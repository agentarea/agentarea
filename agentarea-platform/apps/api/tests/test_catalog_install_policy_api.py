"""The install routes ask the policy engine before installing a catalog item (ADR-0044).

A workspace rule denying a registry, or its trust level, refuses installing a
skill or an agent from it with 403 before anything is installed; a matching
allow rule lets the install through, and with no rule every install proceeds.
Runs the real routes and the real policy check over an in-memory catalog and
rule table; the install itself is a stand-in that reports it was reached.
"""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.skill_service import SkillService
from agentarea_api.api.deps.services import get_agent_service
from agentarea_api.api.v1 import agents, skills
from agentarea_api.api.v1._catalog_install import CatalogInstallPolicy, get_catalog_install_policy
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.base.models import BaseModel
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from agentarea_registry.domain.models import Registry, RegistryItem
from agentarea_registry.infrastructure.repository import RegistryItemRepository
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.ext.compiler import compiles
from sqlalchemy.pool import StaticPool


@compiles(JSONB, "sqlite")
def _jsonb_on_sqlite(type_, compiler, **kw):
    return "JSON"


CALLER = UserContext(user_id="u", workspace_id="acme", admin_workspaces=["acme"])


@pytest_asyncio.fixture
async def session() -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: BaseModel.metadata.create_all(
                c,
                tables=[Registry.__table__, RegistryItem.__table__, PolicyRuleORM.__table__],
            )
        )
    async with async_sessionmaker(engine, expire_on_commit=False)() as s:
        yield s
    await engine.dispose()


async def _item(session: AsyncSession, registry_type: str, trust: str) -> RegistryItem:
    registry = Registry(
        name=f"{registry_type}-{trust}",
        registry_type=registry_type,
        source_type="url",
        source_url="https://example.test/index.json",
        trust=trust,
        mode="upstream" if trust == "community" else "mirror",
    )
    session.add(registry)
    await session.commit()
    return await RegistryItemRepository(session).create(
        registry_id=registry.id, external_id="probe", name="probe"
    )


async def _rule(session: AsyncSession, target: str, effect: PolicyEffect) -> None:
    await PolicyRuleRepository(session, CALLER).create(
        PolicyRule(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id=CALLER.workspace_id,
            target=target,
            effect=effect,
        )
    )
    await session.commit()


@pytest.fixture
def skill_service():
    service = AsyncMock(spec=SkillService)
    service.user_context = CALLER
    # Not found: the test only needs to know whether the install was reached.
    service.install_catalog_skill.return_value = None
    return service


@pytest.fixture
def agent_service():
    service = AsyncMock(spec=AgentService)
    service.install_catalog_agent.return_value = None
    return service


@pytest_asyncio.fixture
async def client(session, skill_service, agent_service):
    app = FastAPI()
    for module in (skills, agents):
        app.include_router(module.router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_user_context] = lambda: CALLER
    app.dependency_overrides[skills.get_skill_service] = lambda: skill_service
    app.dependency_overrides[get_agent_service] = lambda: agent_service
    app.dependency_overrides[get_catalog_install_policy] = lambda: CatalogInstallPolicy(
        session, CALLER
    )
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


def _install(kind: str, item_id) -> str:
    return f"/v1/workspaces/acme/{kind}/{item_id}/install"


@pytest.mark.parametrize("kind", ["skills", "agents"])
async def test_no_rule_lets_the_install_through(
    client, session, skill_service, agent_service, kind
):
    item = await _item(session, kind, "community")

    response = await client.post(_install(kind, item.id))

    assert response.status_code == 404
    installer = (
        skill_service.install_catalog_skill
        if kind == "skills"
        else agent_service.install_catalog_agent
    )
    installer.assert_awaited_once()


@pytest.mark.parametrize("kind", ["skills", "agents"])
async def test_a_deny_on_the_trust_level_refuses_the_install(
    client, session, skill_service, agent_service, kind
):
    item = await _item(session, kind, "community")
    await _rule(session, "registry_trust:community", PolicyEffect.DENY)

    response = await client.post(_install(kind, item.id))

    assert response.status_code == 403
    assert "registry_trust:community" in response.json()["detail"]
    skill_service.install_catalog_skill.assert_not_awaited()
    agent_service.install_catalog_agent.assert_not_awaited()


async def test_a_deny_on_the_registry_refuses_only_that_registry(client, session, skill_service):
    denied = await _item(session, "skills", "community")
    other = await _item(session, "skills", "official")
    await _rule(session, f"registry:{denied.registry_id}", PolicyEffect.DENY)

    assert (await client.post(_install("skills", denied.id))).status_code == 403
    assert (await client.post(_install("skills", other.id))).status_code == 404
    skill_service.install_catalog_skill.assert_awaited_once()


async def test_an_allowlist_admits_only_what_it_names(client, session, skill_service):
    official = await _item(session, "skills", "official")
    community = await _item(session, "skills", "community")
    await _rule(session, "registry_trust:official", PolicyEffect.ALLOW)

    assert (await client.post(_install("skills", official.id))).status_code == 404
    assert (await client.post(_install("skills", community.id))).status_code == 403
    skill_service.install_catalog_skill.assert_awaited_once()


async def test_an_id_that_is_no_catalog_item_is_left_to_the_install(client, session, skill_service):
    await _rule(session, "registry_trust:community", PolicyEffect.DENY)

    response = await client.post(_install("skills", uuid4()))

    assert response.status_code == 404
    skill_service.install_catalog_skill.assert_awaited_once()
