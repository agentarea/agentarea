"""Permission service interface and helper."""

import logging
from abc import ABC, abstractmethod

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class PermissionService(ABC):
    """Abstract permission service. OSS and Enterprise provide implementations."""

    @abstractmethod
    async def check(
        self,
        user_id: str,
        permission: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        """Check if user has permission on a resource.

        Args:
            user_id: The user requesting access.
            permission: Action (view, edit, delete, execute).
            resource_type: Entity type (agent, mcp_server, skill, model, etc.).
            resource_id: ID of the specific resource.

        Returns:
            True if allowed, False if denied.
        """
        ...


async def require_permission(
    permission: str,
    resource_type: str,
    resource_id: str,
    user_id: str,
) -> None:
    """Check permission and raise 403 if denied.

    Resolves PermissionService from the DI container.
    """
    from agentarea_common.di.container import resolve

    perm_service = resolve(PermissionService)
    allowed = await perm_service.check(user_id, permission, resource_type, resource_id)
    if not allowed:
        logger.warning(
            "Permission denied: user=%s permission=%s resource=%s/%s",
            user_id,
            permission,
            resource_type,
            resource_id,
        )
        raise HTTPException(status_code=403, detail="Permission denied")
