"""Unit tests for MCPOAuthLinkService — Task 3.13."""

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from agentarea_mcp.application.oauth_link_service import MCPOAuthLinkService
from agentarea_mcp.domain.auth_models import (
    ACCESS_CONTROL_PUBLIC,
    ACCESS_CONTROL_WORKSPACE,
    MCPOAuthLink,
    MCPOAuthSession,
)


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _link(
    *,
    token: str = "tok123",
    access_control: str = ACCESS_CONTROL_WORKSPACE,
    workspace_id: str = "ws-1",
    is_active: bool = True,
    expires_at: datetime | None = None,
    provider_config: dict | None = None,
) -> MCPOAuthLink:
    link = MagicMock(spec=MCPOAuthLink)
    link.id = uuid4()
    link.token = token
    link.access_control = access_control
    link.workspace_id = workspace_id
    link.is_active = is_active
    link.expires_at = expires_at
    link.provider_config = provider_config or {
        "auth_url": "https://example.com/auth",
        "client_id": "client-id",
        "token_url": "https://example.com/token",
        "scopes": ["openid"],
    }
    link.mcp_instance_id = uuid4()
    return link


def _session(*, expired: bool = False) -> MCPOAuthSession:
    session = MagicMock(spec=MCPOAuthSession)
    session.session_token = "sess-token-abc"
    session.is_expired.return_value = expired
    return session


def _make_service(link_repo=None, session_repo=None):
    link_repo = link_repo or AsyncMock()
    session_repo = session_repo or AsyncMock()
    return MCPOAuthLinkService(link_repo, session_repo), link_repo, session_repo


# ---------------------------------------------------------------------------
# create_link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateLink:
    async def test_creates_link_with_unique_token(self):
        svc, repo, _ = _make_service()
        created = _link()
        repo.create.return_value = created

        result = await svc.create_link(mcp_instance_id=uuid4())

        repo.create.assert_called_once()
        call_kwargs = repo.create.call_args.kwargs
        assert len(call_kwargs["token"]) > 0
        assert result is created

    async def test_creates_link_with_expiry(self):
        svc, repo, _ = _make_service()
        created = _link()
        repo.create.return_value = created

        await svc.create_link(mcp_instance_id=uuid4(), expires_in_days=7)

        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["expires_at"] is not None

    async def test_creates_link_without_expiry_by_default(self):
        svc, repo, _ = _make_service()
        repo.create.return_value = _link()

        await svc.create_link(mcp_instance_id=uuid4())

        call_kwargs = repo.create.call_args.kwargs
        assert call_kwargs["expires_at"] is None


# ---------------------------------------------------------------------------
# get_link_by_token
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestGetLinkByToken:
    async def test_returns_active_link(self):
        svc, repo, _ = _make_service()
        link = _link(is_active=True)
        repo.get_by_token.return_value = link

        result = await svc.get_link_by_token("tok123")

        assert result is link

    async def test_returns_none_for_inactive_link(self):
        svc, repo, _ = _make_service()
        link = _link(is_active=False)
        repo.get_by_token.return_value = link

        result = await svc.get_link_by_token("tok123")

        assert result is None

    async def test_returns_none_when_link_not_found(self):
        svc, repo, _ = _make_service()
        repo.get_by_token.return_value = None

        result = await svc.get_link_by_token("unknown")

        assert result is None

    async def test_deactivates_and_returns_none_for_expired_link(self):
        svc, repo, _ = _make_service()
        past = datetime.utcnow() - timedelta(days=1)
        link = _link(is_active=True, expires_at=past)
        repo.get_by_token.return_value = link

        result = await svc.get_link_by_token("tok123")

        assert result is None
        repo.update.assert_called_once_with(link.id, is_active=False)

    async def test_active_link_with_future_expiry_is_returned(self):
        svc, repo, _ = _make_service()
        future = datetime.utcnow() + timedelta(days=1)
        link = _link(is_active=True, expires_at=future)
        repo.get_by_token.return_value = link

        result = await svc.get_link_by_token("tok123")

        assert result is link


# ---------------------------------------------------------------------------
# revoke_link
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestRevokeLink:
    async def test_revoke_existing_link(self):
        svc, repo, _ = _make_service()
        link = _link()
        repo.get.return_value = link

        result = await svc.revoke_link(link.id)

        assert result is True
        repo.update.assert_called_once_with(link.id, is_active=False)

    async def test_revoke_missing_link_returns_false(self):
        svc, repo, _ = _make_service()
        repo.get.return_value = None

        result = await svc.revoke_link(uuid4())

        assert result is False
        repo.update.assert_not_called()


# ---------------------------------------------------------------------------
# validate_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestValidateSession:
    async def test_valid_session_is_returned(self):
        svc, _, session_repo = _make_service()
        sess = _session(expired=False)
        session_repo.get_by_token.return_value = sess

        result = await svc.validate_session("sess-token-abc")

        assert result is sess

    async def test_expired_session_returns_none(self):
        svc, _, session_repo = _make_service()
        sess = _session(expired=True)
        session_repo.get_by_token.return_value = sess

        result = await svc.validate_session("sess-token-abc")

        assert result is None

    async def test_missing_session_returns_none(self):
        svc, _, session_repo = _make_service()
        session_repo.get_by_token.return_value = None

        result = await svc.validate_session("nonexistent")

        assert result is None


# ---------------------------------------------------------------------------
# check_access_control
# ---------------------------------------------------------------------------


class TestCheckAccessControl:
    def test_public_link_allows_any_workspace(self):
        svc, _, _ = _make_service()
        link = _link(access_control=ACCESS_CONTROL_PUBLIC, workspace_id="ws-owner")

        assert svc.check_access_control(link, "ws-other") is True
        assert svc.check_access_control(link, "ws-owner") is True

    def test_workspace_link_allows_only_matching_workspace(self):
        svc, _, _ = _make_service()
        link = _link(access_control=ACCESS_CONTROL_WORKSPACE, workspace_id="ws-1")

        assert svc.check_access_control(link, "ws-1") is True
        assert svc.check_access_control(link, "ws-2") is False

    def test_unknown_access_control_denies(self):
        svc, _, _ = _make_service()
        link = _link(access_control="custom")

        assert svc.check_access_control(link, "ws-1") is False


# ---------------------------------------------------------------------------
# build_authorization_url
# ---------------------------------------------------------------------------


class TestBuildAuthorizationUrl:
    def test_builds_url_with_required_params(self):
        svc, _, _ = _make_service()
        link = _link(
            provider_config={
                "auth_url": "https://github.com/login/oauth/authorize",
                "client_id": "gh-client-id",
                "scopes": ["read:user", "user:email"],
            }
        )

        url = svc.build_authorization_url(link, "https://app.example.com/callback", "state123")

        assert "https://github.com/login/oauth/authorize" in url
        assert "client_id=gh-client-id" in url
        assert "state=state123" in url
        assert "response_type=code" in url
        assert "redirect_uri=" in url

    def test_default_scopes_used_when_not_specified(self):
        svc, _, _ = _make_service()
        link = _link(
            provider_config={
                "auth_url": "https://example.com/auth",
                "client_id": "cid",
            }
        )

        url = svc.build_authorization_url(link, "https://app.example.com/cb", "s")

        # Default scopes from the service: openid email
        assert "scope=" in url


# ---------------------------------------------------------------------------
# create_session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
class TestCreateSession:
    async def test_creates_session_with_token_and_expiry(self):
        svc, _, session_repo = _make_service()
        link_id = uuid4()

        created_session = MagicMock(spec=MCPOAuthSession)
        session_repo.create.return_value = created_session

        result = await svc.create_session(link_id, {"sub": "user-1"})

        session_repo.create.assert_called_once()
        args = session_repo.create.call_args.args[0]
        assert args.link_id == link_id
        assert len(args.session_token) > 0
        assert args.identity == {"sub": "user-1"}
        assert result is created_session
