"""Service layer for MCP authentication configuration management."""

import json
import logging
from typing import Any
from uuid import UUID

from agentarea_common.infrastructure.secret_manager import BaseSecretManager

from agentarea_mcp.domain.auth_models import (
    AUTH_TYPE_API_KEY,
    AUTH_TYPE_BEARER,
    AUTH_TYPE_OAUTH2,
    MCPAuthConfig,
)
from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository

logger = logging.getLogger(__name__)

# Secret manager key prefix so auth creds are grouped
_SECRET_PREFIX = "mcp_auth_cred"  # noqa: S105


class MissingCredentialsError(Exception):
    """The auth config names credentials that are not there.

    Distinct from OAuthReauthRequiredError: nothing is expired or revoked, the
    stored value is simply absent, so the fix is to enter it rather than to
    re-authorize.
    """


class OAuthReauthRequiredError(Exception):
    """The OAuth session cannot be renewed unattended — the user must reconnect.

    Raised when an access token is expired/rejected and no usable refresh path
    exists (no refresh_token, or the refresh grant itself failed). Callers should
    surface this as an actionable "reconnect with OAuth" state rather than a raw
    upstream 401/403.
    """


def _secret_key(config_id: UUID) -> str:
    return f"{_SECRET_PREFIX}:{config_id}"


class MCPAuthService:
    """Business logic for creating, updating and deleting MCP auth configurations.

    Sensitive credential fields (api_key value, bearer token, client_secret, etc.)
    are stored encrypted via the secret manager.  The ``secret_key`` column on
    ``MCPAuthConfig`` stores the lookup key so they can be retrieved later.
    """

    def __init__(
        self,
        repository: MCPAuthConfigRepository,
        secret_manager: BaseSecretManager,
    ) -> None:
        self._repo = repository
        self._secret_manager = secret_manager

    # ------------------------------------------------------------------
    # Credential helpers
    # ------------------------------------------------------------------

    async def _store_credentials(self, config_id: UUID, credentials: dict[str, Any]) -> str:
        """Encrypt and persist credentials; return the secret lookup key."""
        key = _secret_key(config_id)
        await self._secret_manager.set_secret(key, json.dumps(credentials))
        return key

    async def _load_credentials(self, config: MCPAuthConfig) -> dict[str, Any]:
        """Retrieve and decrypt credentials for a config.

        A config with no secret_key legitimately has no credentials. A config
        that names one which has gone missing is broken, and saying so beats
        returning an empty dict — that ends as an empty Authorization header and
        a 401 from the far end, which reads like the remote server's problem.
        """
        if not config.secret_key:
            return {}
        raw = await self._secret_manager.get_secret(config.secret_key)
        if raw is None:
            raise MissingCredentialsError(
                f"Auth config {config.id} references a secret that no longer exists. "
                "Re-enter its credentials."
            )
        return json.loads(raw)

    async def _delete_credentials(self, config: MCPAuthConfig) -> None:
        if config.secret_key:
            await self._secret_manager.delete_secret(config.secret_key)

    # ------------------------------------------------------------------
    # Auth header injection helpers (used by proxy layer)
    # ------------------------------------------------------------------

    async def get_auth_headers(
        self, config: MCPAuthConfig, *, force_refresh: bool = False
    ) -> dict[str, str]:
        """Return HTTP headers to inject for the given auth config.

        For API key: ``{header_name: header_value}``
        For bearer:  ``{Authorization: Bearer <token>}``
        For oauth2:  ``{Authorization: Bearer <access_token>}`` (after refresh if needed)

        ``force_refresh`` forces an OAuth token refresh even if the stored token
        looks unexpired — used to react to an upstream 401/403. Raises
        :class:`OAuthReauthRequiredError` when the session can't be renewed.
        """
        creds = await self._load_credentials(config)

        if config.auth_type == AUTH_TYPE_API_KEY:
            header_name = config.config.get("header_name", "X-API-Key")
            header_value = creds.get("header_value", "")
            if not header_value:
                # Sending the header empty produces a 401 from the upstream
                # server, which points the user at the wrong system.
                raise MissingCredentialsError(
                    f"Auth config {config.id} has no API key stored. Re-enter its credentials."
                )
            return {header_name: header_value}

        if config.auth_type == AUTH_TYPE_BEARER:
            token = creds.get("token", "")
            if not token:
                raise MissingCredentialsError(
                    f"Auth config {config.id} has no bearer token stored. Re-enter its credentials."
                )
            return {"Authorization": f"Bearer {token}"}

        if config.auth_type == AUTH_TYPE_OAUTH2:
            access_token = await self._get_oauth2_token(config, creds, force_refresh=force_refresh)
            return {"Authorization": f"Bearer {access_token}"}

        return {}

    async def _get_oauth2_token(
        self, config: MCPAuthConfig, creds: dict[str, Any], *, force_refresh: bool = False
    ) -> str:
        """Return a valid OAuth2 access token, refreshing if needed."""
        import time

        access_token = creds.get("access_token", "")
        expires_at = creds.get("expires_at", 0)

        # Refresh if forced, missing, or expired (with 30 s buffer).
        if force_refresh or not access_token or time.time() >= expires_at - 30:
            access_token = await self._refresh_oauth2_token(config, creds)

        return access_token

    async def _refresh_oauth2_token(self, config: MCPAuthConfig, creds: dict[str, Any]) -> str:
        """Obtain a new access token using Client Credentials or Refresh Token flow.

        Raises :class:`OAuthReauthRequiredError` when renewal is impossible (no
        refresh_token and no client_secret for client_credentials) or the token
        endpoint rejects the grant — both mean the user must reconnect.
        """
        import time

        import httpx

        token_url: str = config.config.get("token_url", "")
        client_id: str = config.config.get("client_id", "")
        client_secret: str = creds.get("client_secret", "")
        refresh_token: str = creds.get("refresh_token", "")
        scopes: list[str] = config.config.get("scopes", [])

        if not token_url or not client_id:
            raise ValueError("oauth2 config missing token_url or client_id")

        if refresh_token:
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
            }
            # Public (PKCE/DCR) clients have no secret; only send one if present.
            if client_secret:
                payload["client_secret"] = client_secret
        elif client_secret:
            payload = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": " ".join(scopes),
            }
        else:
            # Nothing to renew with — the AS never issued a refresh_token (e.g.
            # offline_access wasn't granted) and there's no client_secret.
            raise OAuthReauthRequiredError(
                f"auth config {config.id} has no refresh_token or client_secret; reconnect required"
            )

        try:
            async with httpx.AsyncClient() as client:
                resp = await client.post(token_url, data=payload, timeout=10)
                resp.raise_for_status()
                data = resp.json()
        except httpx.HTTPStatusError as exc:
            # 4xx from the token endpoint means the grant is dead (revoked /
            # expired refresh_token) — the user must reconnect.
            if 400 <= exc.response.status_code < 500:
                raise OAuthReauthRequiredError(
                    f"token refresh rejected ({exc.response.status_code}) for auth config "
                    f"{config.id}; reconnect required"
                ) from exc
            raise

        access_token: str = data["access_token"]
        expires_in: int = data.get("expires_in", 900)

        # Persist updated tokens
        creds["access_token"] = access_token
        creds["expires_at"] = time.time() + expires_in
        if "refresh_token" in data:
            creds["refresh_token"] = data["refresh_token"]

        await self._store_credentials(config.id, creds)
        logger.info("Refreshed OAuth2 token for auth config %s", config.id)
        return access_token

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    async def create(
        self,
        name: str,
        auth_type: str,
        config: dict[str, Any],
        credentials: dict[str, Any],
        description: str | None = None,
    ) -> MCPAuthConfig:
        """Create and persist a new auth config, storing creds encrypted."""
        auth_config = MCPAuthConfig(
            name=name,
            auth_type=auth_type,
            config=config,
            description=description,
        )
        auth_config.validate_config()

        # Persist the record first to get an ID
        created = await self._repo.create(
            name=auth_config.name,
            auth_type=auth_config.auth_type,
            config=auth_config.config,
            description=auth_config.description,
        )

        # Store credentials using the generated ID as key
        if credentials:
            key = await self._store_credentials(created.id, credentials)
            created = await self._repo.update(created.id, secret_key=key)
            if created is None:
                raise ValueError(f"MCPAuthConfig {auth_config.id} disappeared during update")

        logger.info("Created MCPAuthConfig %s (type=%s)", created.id, auth_type)
        return created

    async def get(self, config_id: UUID) -> MCPAuthConfig | None:
        return await self._repo.get_by_id(config_id)

    async def list(self) -> list[MCPAuthConfig]:
        return await self._repo.list_all()

    async def update(
        self,
        config_id: UUID,
        name: str | None = None,
        config: dict[str, Any] | None = None,
        credentials: dict[str, Any] | None = None,
        description: str | None = None,
    ) -> MCPAuthConfig | None:
        """Update config fields and optionally rotate credentials."""
        updates: dict[str, Any] = {}
        if name is not None:
            updates["name"] = name
        if config is not None:
            updates["config"] = config
        if description is not None:
            updates["description"] = description

        if updates:
            await self._repo.update(config_id, **updates)

        if credentials is not None:
            existing = await self._repo.get(config_id)
            if existing is None:
                return None
            key = await self._store_credentials(config_id, credentials)
            await self._repo.update(config_id, secret_key=key)

        updated = await self._repo.get(config_id)
        if updated:
            logger.info("Updated MCPAuthConfig %s", config_id)
        return updated

    async def delete(self, config_id: UUID) -> bool:
        """Delete auth config, checking for linked instances first."""
        linked = await self._repo.get_linked_instance_ids(config_id)
        if linked:
            raise ValueError(f"Cannot delete auth config {config_id}: linked to instances {linked}")

        existing = await self._repo.get(config_id)
        if existing is None:
            return False

        await self._delete_credentials(existing)
        return await self._repo.delete(config_id)

    # ------------------------------------------------------------------
    # Validation
    # ------------------------------------------------------------------

    @staticmethod
    def validate_credentials(auth_type: str, credentials: dict[str, Any]) -> None:
        """Raise ValueError if required credential fields are missing for the auth type."""
        if auth_type == AUTH_TYPE_API_KEY:
            if not credentials.get("header_value"):
                raise ValueError("api_key credentials require 'header_value'")
        elif auth_type == AUTH_TYPE_BEARER:
            if not credentials.get("token"):
                raise ValueError("bearer credentials require 'token'")
        elif auth_type == AUTH_TYPE_OAUTH2:
            # For client_credentials flow, client_secret is mandatory
            if not credentials.get("client_secret") and not credentials.get("access_token"):
                raise ValueError(
                    "oauth2 credentials require 'client_secret' or an existing 'access_token'"
                )
