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
        """Retrieve and decrypt credentials for a config."""
        if not config.secret_key:
            return {}
        raw = await self._secret_manager.get_secret(config.secret_key)
        if raw is None:
            return {}
        return json.loads(raw)

    async def _delete_credentials(self, config: MCPAuthConfig) -> None:
        if config.secret_key:
            await self._secret_manager.delete_secret(config.secret_key)

    # ------------------------------------------------------------------
    # Auth header injection helpers (used by proxy layer)
    # ------------------------------------------------------------------

    async def get_auth_headers(self, config: MCPAuthConfig) -> dict[str, str]:
        """Return HTTP headers to inject for the given auth config.

        For API key: ``{header_name: header_value}``
        For bearer:  ``{Authorization: Bearer <token>}``
        For oauth2:  ``{Authorization: Bearer <access_token>}`` (after refresh if needed)
        """
        creds = await self._load_credentials(config)

        if config.auth_type == AUTH_TYPE_API_KEY:
            header_name = config.config.get("header_name", "X-API-Key")
            header_value = creds.get("header_value", "")
            if not header_value:
                logger.warning("api_key auth config %s has no header_value credential", config.id)
            return {header_name: header_value}

        if config.auth_type == AUTH_TYPE_BEARER:
            token = creds.get("token", "")
            return {"Authorization": f"Bearer {token}"}

        if config.auth_type == AUTH_TYPE_OAUTH2:
            access_token = await self._get_oauth2_token(config, creds)
            return {"Authorization": f"Bearer {access_token}"}

        return {}

    async def _get_oauth2_token(self, config: MCPAuthConfig, creds: dict[str, Any]) -> str:
        """Return a valid OAuth2 access token, refreshing if needed."""
        import time

        access_token = creds.get("access_token", "")
        expires_at = creds.get("expires_at", 0)

        # Refresh if expired (with 30 s buffer)
        if not access_token or time.time() >= expires_at - 30:
            access_token = await self._refresh_oauth2_token(config, creds)

        return access_token

    async def _refresh_oauth2_token(self, config: MCPAuthConfig, creds: dict[str, Any]) -> str:
        """Obtain a new access token using Client Credentials or Refresh Token flow."""
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
                "client_secret": client_secret,
            }
        else:
            payload = {
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": " ".join(scopes),
            }

        async with httpx.AsyncClient() as client:
            resp = await client.post(token_url, data=payload, timeout=10)
            resp.raise_for_status()
            data = resp.json()

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
