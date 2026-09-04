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
