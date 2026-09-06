"""Tests for the ReBAC gate on the client-scoped MCP endpoint."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

import agentarea_common.di.container as di
import pytest
from agentarea_api.api.v1.client_mcp import (
    ClientAccessDeniedError,
    _authorize_client_access,
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


class TestTransportSecurity:
    """Host validation belongs to the ingress, not to this mount.

    FastMCP turns DNS-rebinding protection on by default with an empty
    ``allowed_hosts``, which rejects every Host header with 421. The platform
    ``/mcp`` server opts out explicitly because it runs behind a reverse proxy;
    ``/client-mcp`` is the same deployment and must agree, or an authenticated
    harness gets 421 on every call once it finally has a token.
    """

    def test_dns_rebinding_protection_is_disabled(self):
        from agentarea_api.api.v1.client_mcp import client_mcp_server

        security = client_mcp_server.settings.transport_security

        assert security is not None
        assert security.enable_dns_rebinding_protection is False

    def test_agrees_with_the_platform_mcp_mount(self):
        from agentarea_agents_sdk.mcp_server import create_mcp_server
        from agentarea_api.api.v1.client_mcp import client_mcp_server

        platform = create_mcp_server(toolsets=[], name="probe")

        assert (
            client_mcp_server.settings.transport_security.enable_dns_rebinding_protection
            is platform.settings.transport_security.enable_dns_rebinding_protection
        )


class TestClientResolution:
    """A client is addressed by its own id, not by the caller's current workspace.

    The MCP auth path starts every caller on their personal workspace and only
    switches when an X-Workspace-Slug header is present. A harness connecting to
    the ``mcp_endpoint_url`` the API hands out sends no such header, so a
    workspace-scoped lookup silently found nothing and the harness was served an
    empty tool list with HTTP 200. Access is decided by the ReBAC `use` relation
    in ``_authorize_client_access``, not by which workspace the caller happens to
    be sitting in.
    """

    def test_lookup_is_not_filtered_by_the_callers_workspace(self):
        from unittest.mock import MagicMock

        import agentarea_agents.domain.skill_models  # noqa: F401  (registers the mapper)
        from agentarea_common.auth.context import UserContext
        from agentarea_mcp.infrastructure.client_repository import ClientRepository
        from sqlalchemy.dialects import postgresql

        repo = ClientRepository(MagicMock(), UserContext(user_id="u1", workspace_id="personal"))
        query = repo.build_get_by_id_query(CLIENT_ID, any_workspace=True)
        where = str(query.compile(dialect=postgresql.dialect())).split("WHERE", 1)[1]

        assert "workspace_id" not in where

    def test_workspace_scoped_lookup_still_filters(self):
        from unittest.mock import MagicMock

        import agentarea_agents.domain.skill_models  # noqa: F401  (registers the mapper)
        from agentarea_common.auth.context import UserContext
        from agentarea_mcp.infrastructure.client_repository import ClientRepository
        from sqlalchemy.dialects import postgresql

        repo = ClientRepository(MagicMock(), UserContext(user_id="u1", workspace_id="personal"))
        query = repo.build_get_by_id_query(CLIENT_ID, any_workspace=False)
        where = str(query.compile(dialect=postgresql.dialect())).split("WHERE", 1)[1]

        assert "workspace_id" in where


@pytest.mark.asyncio
async def test_list_tools_reports_an_unknown_client_instead_of_returning_none(monkeypatch):
    """An unresolvable client must not look like a client with no tools."""
    from agentarea_api.api.v1 import client_mcp

    async def _missing(_client_id):
        raise client_mcp.ClientNotFoundError(CLIENT_ID)

    monkeypatch.setattr(client_mcp, "_resolve_client_scope", _missing)
    token = client_mcp._client_id_var.set(CLIENT_ID)
    try:
        with pytest.raises(ValueError, match="not found"):
            await client_mcp._list_tools()
    finally:
        client_mcp._client_id_var.reset(token)
