"""Test that system entities (workspace_id='system') are visible to regular users."""
import pytest
from unittest.mock import MagicMock

from agentarea_common.auth.context import UserContext
from agentarea_llm.infrastructure.model_instance_repository import ModelInstanceRepository
from agentarea_llm.infrastructure.provider_config_repository import ProviderConfigRepository
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository


def test_model_instance_repo_includes_system():
    session = MagicMock()
    user_context = UserContext(user_id="user-1", workspace_id="ws-1")
    repo = ModelInstanceRepository(session, user_context)
    ws_filter = repo._get_workspace_filter()
    compiled = str(ws_filter.compile(compile_kwargs={"literal_binds": True}))
    assert "system" in compiled
    assert "ws-1" in compiled


def test_provider_config_repo_includes_system():
    session = MagicMock()
    user_context = UserContext(user_id="user-1", workspace_id="ws-1")
    repo = ProviderConfigRepository(session, user_context)
    ws_filter = repo._get_workspace_filter()
    compiled = str(ws_filter.compile(compile_kwargs={"literal_binds": True}))
    assert "system" in compiled
    assert "ws-1" in compiled


def test_model_spec_repo_includes_system():
    session = MagicMock()
    user_context = UserContext(user_id="user-1", workspace_id="ws-1")
    repo = ModelSpecRepository(session, user_context)
    ws_filter = repo._get_workspace_filter()
    compiled = str(ws_filter.compile(compile_kwargs={"literal_binds": True}))
    assert "system" in compiled
    assert "ws-1" in compiled
