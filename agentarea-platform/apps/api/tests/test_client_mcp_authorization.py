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
