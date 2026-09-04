"""``model_id`` must name a model instance the runtime can actually resolve.

The API used to accept any string that looked vaguely like a model name, so a
typo or a model-spec id sailed through agent creation and only blew up hours
later inside ``call_llm_activity`` as ``Invalid model_id:``. Validation now
lives in the service, which every caller goes through — REST, the MCP toolset,
and import/export alike.
"""

from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService, InvalidModelIdError
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill, agent_skills_table
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_common.audit.models import AuditEventORM
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec
from agentarea_secrets.models import EncryptedSecret
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory():
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
                    # ProviderConfig.api_key_secret_id references encrypted_secrets
                    # (#350). Creating the referring table without this one leaves a
                    # dangling foreign key: harmless while SQLite has FK enforcement
                    # off, but a flush fails the moment an earlier test in the same
                    # session has turned it on — which is why this only broke once
                    # the gate started collecting the whole suite.
                    EncryptedSecret.__table__,
                ],
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


def _context(workspace_id: str = "ws-a") -> UserContext:
    return UserContext(user_id="user-a", workspace_id=workspace_id)


class _AllowAllAuthz:
    async def can_write_workspace(self, _user_context, _workspace_id) -> bool:
        return True


class _NullBroker:
    async def publish(self, _event) -> None:
        pass


def _service(session: AsyncSession, context: UserContext) -> AgentService:
    return AgentService(RepositoryFactory(session, context), _NullBroker(), _AllowAllAuthz())


async def _seed_model_instance(session: AsyncSession, workspace_id: str = "ws-a") -> ModelInstance:
    provider_spec = ProviderSpec(
        id=uuid4(),
        provider_key=f"openai-{workspace_id}",
        name="OpenAI",
        provider_type="openai",
        workspace_id=workspace_id,
        created_by="user-a",
    )
    provider_config = ProviderConfig(
        id=uuid4(),
        provider_spec_id=provider_spec.id,
        name="OpenAI (test)",
        workspace_id=workspace_id,
        created_by="user-a",
    )
    model_spec = ModelSpec(
        id=uuid4(),
        provider_spec_id=provider_spec.id,
        model_name="gpt-4o",
        display_name="GPT-4o",
        context_window=128000,
        workspace_id=workspace_id,
        created_by="user-a",
    )
    instance = ModelInstance(
        id=uuid4(),
        provider_config_id=provider_config.id,
        model_spec_id=model_spec.id,
        name="gpt-4o",
        workspace_id=workspace_id,
        created_by="user-a",
    )
    session.add_all([provider_spec, provider_config, model_spec, instance])
    await session.flush()
    return instance


async def test_create_accepts_a_real_model_instance(session_factory):
    async with session_factory() as session:
        context = _context()
        instance = await _seed_model_instance(session)

        agent = await _service(session, context).create_agent(
            AgentCreate(name="Bound", model_id=str(instance.id))
        )

        assert agent.model_id == str(instance.id)


async def test_create_rejects_a_bare_model_name(session_factory):
    """The regression: 'gpt-4o' used to pass and fail only at run time."""
    async with session_factory() as session:
        with pytest.raises(InvalidModelIdError, match="expected the UUID"):
            await _service(session, _context()).create_agent(
                AgentCreate(name="Named", model_id="gpt-4o")
            )


async def test_create_rejects_a_uuid_that_is_not_a_model_instance(session_factory):
    """A model *spec* id is a UUID, so shape checks alone would let it through."""
    async with session_factory() as session:
        with pytest.raises(InvalidModelIdError, match="does not exist in this workspace"):
            await _service(session, _context()).create_agent(
                AgentCreate(name="Ghost", model_id=str(uuid4()))
            )


async def test_create_rejects_an_instance_from_another_workspace(session_factory):
    async with session_factory() as session:
        instance = await _seed_model_instance(session, workspace_id="ws-other")

        with pytest.raises(InvalidModelIdError, match="does not exist in this workspace"):
            await _service(session, _context("ws-a")).create_agent(
                AgentCreate(name="Borrowed", model_id=str(instance.id))
            )


async def test_unbound_agent_is_allowed_and_empty_string_normalises_to_none(session_factory):
    """A catalog fork legitimately starts with no model; '' is that state misspelled."""
    async with session_factory() as session:
        service = _service(session, _context())

        omitted = await service.create_agent(AgentCreate(name="Unbound"))
        blank = await service.create_agent(AgentCreate(name="Blank", model_id="   "))

        assert omitted.model_id is None
        assert blank.model_id is None


async def test_update_is_validated_too(session_factory):
    async with session_factory() as session:
        context = _context()
        service = _service(session, context)
        agent = await service.create_agent(AgentCreate(name="Editable"))

        with pytest.raises(InvalidModelIdError):
            await service.update_agent(agent.id, AgentUpdate(model_id="claude-3-5-sonnet"))


async def test_update_can_bind_a_model_later(session_factory):
    async with session_factory() as session:
        context = _context()
        service = _service(session, context)
        agent = await service.create_agent(AgentCreate(name="Later"))
        instance = await _seed_model_instance(session)

        updated = await service.update_agent(agent.id, AgentUpdate(model_id=str(instance.id)))

        assert updated is not None
        assert updated.model_id == str(instance.id)
