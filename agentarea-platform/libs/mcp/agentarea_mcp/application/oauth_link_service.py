"""Service for managing OAuth-protected shareable MCP links and their sessions."""

import logging
import secrets
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

from agentarea_mcp.domain.auth_models import (
    ACCESS_CONTROL_PUBLIC,
    ACCESS_CONTROL_WORKSPACE,
    MCPOAuthLink,
    MCPOAuthSession,
)
from agentarea_mcp.infrastructure.auth_repository import (
    MCPOAuthLinkRepository,
    MCPOAuthSessionRepository,
)

logger = logging.getLogger(__name__)

# Default session lifetime
SESSION_TTL_HOURS = 24
# Token byte length for URL safety
LINK_TOKEN_BYTES = 32


class MCPOAuthLinkService:
    """Manage OAuth link lifecycle: creation, revocation, session management."""

    def __init__(
        self,
        link_repo: MCPOAuthLinkRepository,
        session_repo: MCPOAuthSessionRepository,
    ) -> None:
        self._links = link_repo
        self._sessions = session_repo

    # ------------------------------------------------------------------
    # Link management
    # ------------------------------------------------------------------

    async def create_link(
        self,
        mcp_instance_id: UUID,
        access_control: str = ACCESS_CONTROL_WORKSPACE,
        provider_config: dict[str, Any] | None = None,
        expires_in_days: int | None = None,
    ) -> MCPOAuthLink:
        """Generate a new OAuth-protected link for a container MCP instance."""
        token = secrets.token_urlsafe(LINK_TOKEN_BYTES)
        expires_at: datetime | None = None
        if expires_in_days:
            expires_at = datetime.utcnow() + timedelta(days=expires_in_days)

        link = await self._links.create(
            mcp_instance_id=mcp_instance_id,
            token=token,
            access_control=access_control,
            provider_config=provider_config or {},
            expires_at=expires_at,
        )
        logger.info("Created OAuth link %s for instance %s", link.id, mcp_instance_id)
        return link

    async def get_link(self, link_id: UUID) -> MCPOAuthLink | None:
        return await self._links.get(link_id)

    async def get_link_by_token(self, token: str) -> MCPOAuthLink | None:
        link = await self._links.get_by_token(token)
        if link is None:
            return None
        # Auto-expire check
        if link.expires_at and datetime.utcnow() >= link.expires_at:
            await self._links.update(link.id, is_active=False)
            return None
        if not link.is_active:
            return None
        return link

    async def get_active_link_for_instance(self, mcp_instance_id: UUID) -> MCPOAuthLink | None:
        """Return the single active OAuth link for an instance, or None."""
        links = await self._links.list_by_instance(mcp_instance_id)
        for link in links:
            if link.is_active:
                if link.expires_at and datetime.utcnow() >= link.expires_at:
                    await self._links.update(link.id, is_active=False)
                    continue
                return link
        return None

    async def list_links(self, mcp_instance_id: UUID) -> list[MCPOAuthLink]:
        return await self._links.list_by_instance(mcp_instance_id)

    async def revoke_link(self, link_id: UUID) -> bool:
        """Immediately deactivate an OAuth link."""
        link = await self._links.get(link_id)
        if link is None:
            return False
        await self._links.update(link_id, is_active=False)
        logger.info("Revoked OAuth link %s", link_id)
        return True

    async def record_access(self, link_id: UUID) -> None:
        """Increment usage counter and update last_accessed_at."""
        await self._links.increment_access_count(link_id)

    # ------------------------------------------------------------------
    # Session management
    # ------------------------------------------------------------------

    async def create_session(
        self,
        link_id: UUID,
        identity: dict[str, Any],
        ttl_hours: int = SESSION_TTL_HOURS,
    ) -> MCPOAuthSession:
        """Issue a new session after successful OAuth callback."""
        session_token = secrets.token_urlsafe(48)
        expires_at = datetime.utcnow() + timedelta(hours=ttl_hours)
        session = MCPOAuthSession(
            link_id=link_id,
            session_token=session_token,
            expires_at=expires_at,
            identity=identity,
        )
        created = await self._sessions.create(session)
        logger.info("Created OAuth session for link %s", link_id)
        return created

    async def validate_session(self, session_token: str) -> MCPOAuthSession | None:
        """Return a valid session or None if expired / not found."""
        session = await self._sessions.get_by_token(session_token)
        if session is None:
            return None
        if session.is_expired():
            return None
        return session

    # ------------------------------------------------------------------
    # OAuth Authorization Code flow helpers
    # ------------------------------------------------------------------

    def build_authorization_url(
        self, link: MCPOAuthLink, redirect_uri: str, state: str
    ) -> str:
        """Construct the provider's authorization URL for the OAuth flow."""
        cfg = link.provider_config
        auth_url: str = cfg.get("auth_url", "")
        client_id: str = cfg.get("client_id", "")
        scopes: list[str] = cfg.get("scopes", ["openid", "email"])

        import urllib.parse

        params = {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": " ".join(scopes),
            "state": state,
        }
        return f"{auth_url}?{urllib.parse.urlencode(params)}"

    async def exchange_code_for_identity(
        self,
        link: MCPOAuthLink,
        code: str,
        redirect_uri: str,
        client_secret: str,
    ) -> dict[str, Any]:
        """Exchange an authorization code for tokens and return identity claims."""
        import httpx

        cfg = link.provider_config
        token_url: str = cfg.get("token_url", "")
        client_id: str = cfg.get("client_id", "")
        userinfo_url: str = cfg.get("userinfo_url", "")

        async with httpx.AsyncClient() as client:
            resp = await client.post(
                token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "client_id": client_id,
                    "client_secret": client_secret,
                },
                headers={"Accept": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            tokens = resp.json()

        access_token: str = tokens.get("access_token", "")

        # Fetch identity from userinfo endpoint if available
        if userinfo_url and access_token:
            async with httpx.AsyncClient() as client:
                ui_resp = await client.get(
                    userinfo_url,
                    headers={"Authorization": f"Bearer {access_token}"},
                    timeout=10,
                )
                if ui_resp.status_code == 200:
                    return ui_resp.json()

        # Fall back to JWT claims in id_token if present
        id_token: str = tokens.get("id_token", "")
        if id_token:
            return _decode_jwt_claims(id_token)

        return {"sub": "unknown"}

    def check_access_control(
        self, link: MCPOAuthLink, requesting_workspace_id: str
    ) -> bool:
        """Return True if the given workspace is allowed to use this link."""
        if link.access_control == ACCESS_CONTROL_PUBLIC:
            return True
        if link.access_control == ACCESS_CONTROL_WORKSPACE:
            return link.workspace_id == requesting_workspace_id
        return False


def _decode_jwt_claims(token: str) -> dict[str, Any]:
    """Decode JWT payload without verification (claims only, not for auth decisions)."""
    import base64
    import json

    try:
        parts = token.split(".")
        if len(parts) < 2:
            return {}
        padding = 4 - len(parts[1]) % 4
        payload = base64.urlsafe_b64decode(parts[1] + "=" * padding)
        return json.loads(payload)
    except Exception:
        return {}
