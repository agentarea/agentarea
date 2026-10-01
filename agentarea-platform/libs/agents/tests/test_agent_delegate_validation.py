"""Delegates are checked when an agent is written, never when it is read.

A remote delegate's ``auth_secret_name`` makes the worker send that workspace
secret to ``a2a_url``, so pointing a secret at a URL is credential use: only a
workspace admin may bind one, and only to a secret no connection manages.
"""

from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService, InvalidDelegateError
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_agents.schemas.import_export import TOOL_CONFIG_ADAPTER
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.testing import install_graph_ownership_stub
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec
from agentarea_secrets.models import EncryptedSecret
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

URL = "https://x.a2a.agentarea.ru"


@pytest.fixture(autouse=True)
def _graph(monkeypatch):
    return install_graph_ownership_stub(monkeypatch)


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[
                    Agent.__table__,
                    Skill.__table__,
                    agent_skills_table,
                    PolicyRuleORM.__table__,
                    AuditEventORM.__table__,
                    ProviderSpec.__table__,
                    ProviderConfig.__table__,
                    ModelSpec.__table__,
                    ModelInstance.__table__,
                    EncryptedSecret.__table__,
                ],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as s:
            yield s
    finally:
        await engine.dispose()


class _Authz:
    def __init__(self, admin: bool):
        self.admin = admin

    async def can_write_workspace(self, _user_context, _workspace_id) -> bool:
        return True

    async def can_administer_workspace(self, _user_context, _workspace_id) -> bool:
        return self.admin


class _NullBroker:
    async def publish(self, _event) -> None:
        pass


def _service(session: AsyncSession, *, admin: bool) -> AgentService:
    context = UserContext(user_id="user-a", workspace_id="ws-a")
    return AgentService(RepositoryFactory(session, context), _NullBroker(), _Authz(admin))


async def _secret(session: AsyncSession, name: str, owner_type: str | None = None) -> None:
    session.add(
        EncryptedSecret(
            id=uuid4(),
            workspace_id="ws-a",
            secret_name=name,
            encrypted_value="x",
            owner_type=owner_type,
            created_by="user-a",
        )
    )
    await session.flush()


def _remote(name: str = "docs-writer", url: str = URL, secret: str | None = "aadocs-key"):
    settings: dict = {"a2a_url": url}
    if secret:
        settings["auth_secret_name"] = secret
    return {"type": "agent", "name": name, "settings": settings}


def _create(tools: list[dict]) -> AgentCreate:
    return AgentCreate(name=f"agent-{uuid4().hex[:6]}", description="", instruction="", tools=tools)


async def test_an_admin_binds_a_workspace_secret_to_a_remote_delegate(session):
    await _secret(session, "aadocs-key")

    agent = await _service(session, admin=True).create_agent(_create([_remote()]))

    assert agent.tools[0]["settings"]["auth_secret_name"] == "aadocs-key"  # pragma: allowlist secret


async def test_a_member_may_not_bind_a_secret(session):
    await _secret(session, "aadocs-key")

    with pytest.raises(PermissionError, match="admin"):
        await _service(session, admin=False).create_agent(_create([_remote()]))


async def test_a_member_may_add_a_remote_delegate_without_a_secret(session):
    agent = await _service(session, admin=False).create_agent(_create([_remote(secret=None)]))

    assert agent.tools[0]["settings"]["a2a_url"] == URL


async def test_a_member_may_keep_a_bound_secret_while_editing_the_rest(session):
    await _secret(session, "aadocs-key")
    agent = await _service(session, admin=True).create_agent(_create([_remote()]))

    updated = await _service(session, admin=False).update_agent(
        agent.id, AgentUpdate(tools=[_remote()], instruction="be brief")
    )

    assert updated is not None
    assert updated.instruction == "be brief"


async def test_a_member_may_not_repoint_a_bound_secret(session):
    await _secret(session, "aadocs-key")
    agent = await _service(session, admin=True).create_agent(_create([_remote()]))

    with pytest.raises(PermissionError, match="admin"):
        await _service(session, admin=False).update_agent(
            agent.id, AgentUpdate(tools=[_remote(url="https://attacker.example/rpc")])
        )


async def test_a_missing_secret_is_refused_by_name(session):
    with pytest.raises(InvalidDelegateError, match="aadocs-key"):
        await _service(session, admin=True).create_agent(_create([_remote()]))


async def test_a_managed_secret_is_refused(session):
    await _secret(session, "oauth-token", owner_type="connection")

    with pytest.raises(InvalidDelegateError, match="managed"):
        await _service(session, admin=True).create_agent(_create([_remote(secret="oauth-token")]))  # pragma: allowlist secret


@pytest.mark.parametrize("url", ["", "ftp://host/rpc", "agentarea.ru/rpc", "https://"])
async def test_a_remote_delegate_needs_an_http_url(session, url):
    with pytest.raises(InvalidDelegateError, match="a2a_url"):
        await _service(session, admin=True).create_agent(_create([_remote(url=url, secret=None)]))


async def test_a_pasted_url_is_stored_without_surrounding_spaces(session):
    agent = await _service(session, admin=True).create_agent(
        _create([_remote(url=f"  {URL} ", secret=None)])
    )

    assert agent.tools[0]["settings"]["a2a_url"] == URL


@pytest.mark.parametrize(
    "pasted", [f"{URL}/", f"{URL}/.well-known/agent-card.json", f" {URL}/.well-known/agent-card.json "]
)
async def test_a_pasted_card_url_is_stored_as_the_agents_address(session, pasted):
    agent = await _service(session, admin=True).create_agent(
        _create([_remote(url=pasted, secret=None)])
    )

    assert agent.tools[0]["settings"]["a2a_url"] == URL


async def test_an_edited_url_is_stored_without_surrounding_spaces(session):
    service = _service(session, admin=True)
    agent = await service.create_agent(_create([_remote(secret=None)]))

    updated = await service.update_agent(
        agent.id, AgentUpdate(tools=[_remote(url=f"{URL}  ", secret=None)])
    )

    assert updated is not None
    assert updated.tools[0]["settings"]["a2a_url"] == URL


async def test_a_secret_without_a_url_is_refused(session):
    await _secret(session, "aadocs-key")
    tool = {"type": "agent", "name": "docs-writer", "settings": {"auth_secret_name": "aadocs-key"}}  # pragma: allowlist secret

    with pytest.raises(InvalidDelegateError, match="a2a_url"):
        await _service(session, admin=True).create_agent(_create([tool]))


async def test_a_local_delegate_must_name_an_agent_here(session):
    with pytest.raises(InvalidDelegateError, match="ghost"):
        await _service(session, admin=True).create_agent(
            _create([{"type": "agent", "name": "ghost"}])
        )


async def test_a_local_delegate_naming_an_agent_here_is_kept(session):
    service = _service(session, admin=False)
    target = await service.create_agent(_create([]))

    agent = await service.create_agent(_create([{"type": "agent", "name": target.name}]))

    assert agent.tools == [{"type": "agent", "name": target.name}]


async def test_delegates_whose_tool_names_collide_are_refused(session):
    with pytest.raises(InvalidDelegateError, match="delegate_to_My_Agent"):
        await _service(session, admin=True).create_agent(
            _create([_remote("My Agent", secret=None), _remote("My-Agent", secret=None)])
        )


def test_a_stored_delegate_with_a_bad_url_still_reads():
    stored = {"type": "agent", "name": "old", "settings": {"a2a_url": "not a url"}}

    assert TOOL_CONFIG_ADAPTER.validate_python(stored).settings.a2a_url == "not a url"
