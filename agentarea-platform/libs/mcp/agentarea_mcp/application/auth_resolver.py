"""Shared auth-header resolver for every outbound connection transport."""

from collections.abc import Awaitable, Callable
from uuid import UUID

from agentarea_common.infrastructure.secret_manager import BaseSecretManager

from agentarea_mcp.application.auth_service import MCPAuthService
from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository


def build_auth_header_resolver(
    repository_factory,
    secret_manager: BaseSecretManager,
    managed_secret_manager: BaseSecretManager,
) -> Callable[[UUID, str, list[str] | None], Awaitable[dict[str, str]]]:
    """Resolve a workspace auth config, with platform credentials when requested."""
    repository = repository_factory.create_repository(MCPAuthConfigRepository)
    service = MCPAuthService(repository, secret_manager, managed_secret_manager)

    async def resolve(
        config_id: UUID,
        request_origin: str,
        allowed_origins: list[str] | None,
    ) -> dict[str, str]:
        config = await service.get(config_id)
        if config is None:
            raise ValueError(f"Auth config {config_id} not found in this workspace")
        if config.config.get("credential_mode") == "managed":
            if not allowed_origins or request_origin not in allowed_origins:
                raise ValueError(
                    "Managed OAuth credentials can only be used by their trusted catalog connection"
                )
        return await service.get_auth_headers(config)

    return resolve
