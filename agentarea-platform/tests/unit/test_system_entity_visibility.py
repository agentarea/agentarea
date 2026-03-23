"""Test that system entities (workspace_id='system') are visible to regular users.

The AuthorizationService resolves accessible_workspaces on UserContext during auth.
The base WorkspaceScopedRepository uses accessible_workspaces for query filtering.
"""
import pytest
from unittest.mock import MagicMock

from agentarea_common.auth.context import UserContext
from agentarea_common.auth.simple_authorization import SimpleAuthorizationService
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository


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
