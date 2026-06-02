"""Test that system entities (workspace_id='system') are visible to regular users.

The AuthorizationService resolves accessible_workspaces on UserContext during auth.
The base WorkspaceScopedRepository uses accessible_workspaces for query filtering.
"""
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.simple_authorization import SimpleAuthorizationService
from agentarea_llm.domain.models import ModelInstance, ProviderConfig
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository


def _user_context_with_system(workspace_id: str = "ws-1") -> UserContext:
    """Create a UserContext with accessible_workspaces including system."""
    return UserContext(
        user_id="user-1",
        workspace_id=workspace_id,
        accessible_workspaces=[workspace_id, "system"],
    )


def test_model_instance_repo_includes_system():
    session = MagicMock()
    user_context = _user_context_with_system()
    repo = ModelInstanceRepository(session, user_context)
    ws_filter = repo._get_workspace_filter()
    compiled = str(ws_filter.compile(compile_kwargs={"literal_binds": True}))
    assert "system" in compiled
    assert "ws-1" in compiled


def test_provider_config_repo_includes_system():
    session = MagicMock()
    user_context = _user_context_with_system()
    repo = ProviderConfigRepository(session, user_context)
    ws_filter = repo._get_workspace_filter()
    compiled = str(ws_filter.compile(compile_kwargs={"literal_binds": True}))
    assert "system" in compiled
    assert "ws-1" in compiled


def test_model_spec_repo_includes_system():
    session = MagicMock()
    user_context = _user_context_with_system()
    repo = ModelSpecRepository(session, user_context)
    ws_filter = repo._get_workspace_filter()
    compiled = str(ws_filter.compile(compile_kwargs={"literal_binds": True}))
    assert "system" in compiled
    assert "ws-1" in compiled


@pytest.mark.asyncio
async def test_provider_config_repo_create_scopes_to_current_workspace(monkeypatch):
    session = MagicMock()
    session.commit = AsyncMock()
    user_context = _user_context_with_system()
    repo = ProviderConfigRepository(session, user_context)
    monkeypatch.setattr(repo, "get_with_relations", AsyncMock(return_value=None))

    # Pre-populate workspace_id AND created_by with attacker-controlled values
    # to prove the repo unconditionally overwrites both from UserContext (no
    # silent fallback — see project rule "never fall back to system user_id").
    config = ProviderConfig(
        provider_spec_id=uuid4(),
        name="Test provider",
        api_key="secret-ref",
        workspace_id="wrong-workspace",
        created_by="attacker-user",
    )

    created = await repo.create_config(config)

    assert created is config
    assert config.workspace_id == "ws-1"
    assert config.created_by == "user-1"
    session.add.assert_called_once_with(config)
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_provider_config_repo_has_update_config(monkeypatch):
    """Regression: ProviderService.update_provider_config calls
    repo.update_config(config). Missing method raised AttributeError on every
    PUT/PATCH /provider-configs/{id} and the providers_toolset update path.
    The method must delegate to the base update_from_entity contract
    (mutated domain object → persisted + refreshed record).
    """
    session = MagicMock()
    user_context = _user_context_with_system()
    repo = ProviderConfigRepository(session, user_context)

    config = ProviderConfig(
        id=uuid4(),
        provider_spec_id=uuid4(),
        name="Renamed provider",
        api_key="secret-ref",
        workspace_id="ws-1",
        created_by="user-1",
    )

    update_from_entity_mock = AsyncMock(return_value=config)
    monkeypatch.setattr(repo, "update_from_entity", update_from_entity_mock)
    monkeypatch.setattr(repo, "get_with_relations", AsyncMock(return_value=config))

    result = await repo.update_config(config)

    update_from_entity_mock.assert_awaited_once_with(config)
    assert result is config


@pytest.mark.asyncio
async def test_model_instance_repo_create_scopes_to_current_workspace(monkeypatch):
    session = MagicMock()
    session.commit = AsyncMock()
    user_context = _user_context_with_system()
    repo = ModelInstanceRepository(session, user_context)
    monkeypatch.setattr(repo, "get_with_relations", AsyncMock(return_value=None))

    # Same overwrite contract as ProviderConfig — supplied created_by must be
    # ignored and replaced with the calling UserContext.user_id.
    instance = ModelInstance(
        provider_config_id=uuid4(),
        model_spec_id=uuid4(),
        name="Test model",
        workspace_id="wrong-workspace",
        created_by="attacker-user",
    )

    created = await repo.create_instance(instance)

    assert created is instance
    assert instance.workspace_id == "ws-1"
    assert instance.created_by == "user-1"
    session.add.assert_called_once_with(instance)
    session.commit.assert_awaited_once()


def test_default_user_context_only_own_workspace():
    """Without AuthorizationService, UserContext defaults to own workspace only."""
    user_context = UserContext(user_id="user-1", workspace_id="ws-1")
    assert user_context.accessible_workspaces == ["ws-1"]


@pytest.mark.asyncio
async def test_simple_authorization_includes_system():
    """SimpleAuthorizationService grants access to own + system workspace."""
    authz = SimpleAuthorizationService()
    user_context = UserContext(user_id="user-1", workspace_id="ws-1")
    workspaces = await authz.get_accessible_workspaces(user_context)
    assert "ws-1" in workspaces
    assert "system" in workspaces


@pytest.mark.asyncio
async def test_simple_authorization_write_own_workspace():
    """SimpleAuthorizationService allows writes only to own workspace."""
    authz = SimpleAuthorizationService()
    user_context = UserContext(user_id="user-1", workspace_id="ws-1")
    assert await authz.can_write_workspace(user_context, "ws-1") is True
    assert await authz.can_write_workspace(user_context, "system") is False
    assert await authz.can_write_workspace(user_context, "other-ws") is False
