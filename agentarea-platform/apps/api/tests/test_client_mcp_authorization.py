"""Tests for the ReBAC gate on the client-scoped MCP endpoint."""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import agentarea_common.di.container as di
import pytest
from agentarea_common.auth.context import UserPrincipal
from agentarea_api.api.v1.client_mcp import (
    ClientAccessDeniedError,
    _authorize_client_access,
    _resolve_client_scope,
)

CLIENT_ID = "11111111-1111-1111-1111-111111111111"


def _ctx(user_id="user-1", client_id=None):
    return SimpleNamespace(user_id=user_id, client_id=client_id)


def _patch_permission(monkeypatch, allowed: bool):
    service = SimpleNamespace(check=AsyncMock(return_value=allowed))
    monkeypatch.setattr(di, "resolve", lambda _iface: service)
    return service


@pytest.mark.asyncio
async def test_client_credentials_principal_is_trusted_for_its_own_bundle(monkeypatch):
    service = _patch_permission(monkeypatch, allowed=False)

    # Token subject IS the client -> no graph check, always allowed.
    await _authorize_client_access(_ctx(client_id=CLIENT_ID), CLIENT_ID)

    service.check.assert_not_awaited()


@pytest.mark.asyncio
async def test_user_with_use_relation_is_allowed(monkeypatch):
    service = _patch_permission(monkeypatch, allowed=True)

    await _authorize_client_access(_ctx(), CLIENT_ID)

    service.check.assert_awaited_once_with("user-1", "use", "client", CLIENT_ID)


@pytest.mark.asyncio
async def test_user_without_use_relation_is_denied(monkeypatch):
    _patch_permission(monkeypatch, allowed=False)

    with pytest.raises(ClientAccessDeniedError):
        await _authorize_client_access(_ctx(), CLIENT_ID)


@pytest.mark.asyncio
async def test_client_endpoint_binds_context_to_clients_workspace():
    """The resource chooses workspace server-side; no token claim/header is needed."""
    principal = UserPrincipal(
        user_id="user-1", accessible_workspaces=["personal-workspace", "client-workspace"]
    )
    client = SimpleNamespace(
        id=CLIENT_ID,
        name="Codex",
        description=None,
        workspace_id="client-workspace",
        source_project_id=None,
        mcp_instances=[],
        skills=[],
    )
    client_repository = MagicMock()
    client_repository.get_by_id = AsyncMock(return_value=client)
    client_repository.get_instance_namespaces = AsyncMock(return_value={})
    repository_class = MagicMock(return_value=client_repository)
    repository_class.locate_workspace = AsyncMock(return_value="client-workspace")

    session = MagicMock()

    @asynccontextmanager
    async def read_session():
        yield session

    database = MagicMock()
    database.read_session = read_session
    connection_manager = MagicMock()
    connection_manager.get_event_broker = AsyncMock(return_value=MagicMock())

    def make_secret_manager(*, session, user_context):
        assert user_context.workspace_id == "client-workspace"
        assert user_context.workspace_slug == "client-slug"
        return MagicMock()

    with (
        patch(
            "agentarea_agents_sdk.mcp_server.auth.get_mcp_user_context",
            return_value=principal,
        ),
        patch(
            "agentarea_common.workspaces.lookup.workspace_slug_for",
            new=AsyncMock(return_value="client-slug"),
        ),
        patch("agentarea_common.config.database.get_database", return_value=database),
        patch(
            "agentarea_common.infrastructure.connection_manager.get_connection_manager",
            return_value=connection_manager,
        ),
        patch(
            "agentarea_secrets.secret_manager_factory.get_real_secret_manager",
            side_effect=make_secret_manager,
        ) as get_secret_manager,
        patch(
            "agentarea_mcp.infrastructure.client_repository.ClientRepository",
            new=repository_class,
        ),
        patch(
            "agentarea_mcp.application.service.MCPServerInstanceService",
            return_value=MagicMock(),
        ),
        patch(
            "agentarea_api.api.v1.client_mcp._authorize_client_access",
            new=AsyncMock(),
        ),
    ):
        proxy, skills = await _resolve_client_scope(CLIENT_ID)

    assert proxy is not None
    assert skills == {}
    repository_class.locate_workspace.assert_awaited_once_with(
        session, CLIENT_ID, ["personal-workspace", "client-workspace"]
    )
    client_repository.get_by_id.assert_awaited_once_with(CLIENT_ID)
    bound = repository_class.call_args.args[1]
    assert bound.workspace_id == "client-workspace"
    get_secret_manager.assert_called_once_with(session=session, user_context=bound)


@pytest.mark.asyncio
async def test_client_resource_lookup_is_limited_to_accessible_workspaces():
    """The cross-workspace resource lookup must use only the resolved allowlist."""
    import agentarea_agents.domain.skill_models  # noqa: F401
    import agentarea_mcp.domain.mpc_server_instance_model  # noqa: F401
    from agentarea_mcp.infrastructure.client_repository import ClientRepository

    result = MagicMock()
    result.scalar_one_or_none.return_value = None
    session = MagicMock()
    session.execute = AsyncMock(return_value=result)

    await ClientRepository.locate_workspace(
        session, CLIENT_ID, ["personal-workspace", "client-workspace"]
    )

    statement = session.execute.await_args.args[0]
    params = statement.compile().params
    assert CLIENT_ID in params.values()
    assert ["personal-workspace", "client-workspace"] in params.values()


class TestTransportSecurity:
    """Host validation belongs to the ingress, not to this mount."""

    @staticmethod
    def _security(server):
        from mcp.server.transport_security import TransportSecuritySettings

        server.streamable_http_app(
            streamable_http_path="/",
            stateless_http=True,
            transport_security=TransportSecuritySettings(enable_dns_rebinding_protection=False),
        )
        return server.session_manager.security_settings

    def test_dns_rebinding_protection_is_disabled(self):
        from agentarea_api.api.v1.client_mcp import client_mcp_server

        security = self._security(client_mcp_server)

        assert security is not None
        assert security.enable_dns_rebinding_protection is False

    def test_agrees_with_the_platform_mcp_mount(self):
        from agentarea_agents_sdk.mcp_server import create_mcp_server
        from agentarea_api.api.v1.client_mcp import client_mcp_server

        platform = create_mcp_server(toolsets=[], name="probe", workspace_argument=True)

        assert self._security(client_mcp_server).enable_dns_rebinding_protection is (
            self._security(platform).enable_dns_rebinding_protection
        )
