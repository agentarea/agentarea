"""Permission service interface and helper."""

import logging
from abc import ABC, abstractmethod
from typing import Protocol

from fastapi import HTTPException

logger = logging.getLogger(__name__)


class GraphCaller(Protocol):
    """Anything that names the subject a graph check is about."""

    @property
    def graph_subject(self) -> str: ...


class PermissionService(ABC):
    """Abstract permission service. OSS and Enterprise provide implementations."""

    @abstractmethod
    async def check(
        self,
        subject: str,
        permission: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        """Check if a subject has permission on a resource.

        Args:
            subject: The graph subject asking: ``User:<id>`` or ``Agent:<id>``.
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
    caller: GraphCaller,
) -> None:
    """Check the caller's subject has ``permission`` and raise 403 if not.

    Resolves PermissionService from the DI container. A run asks as its agent,
    a request as its user: the caller says which.
    """
    from agentarea_common.di.container import resolve

    subject = caller.graph_subject
    perm_service = resolve(PermissionService)
    allowed = await perm_service.check(subject, permission, resource_type, resource_id)
    if not allowed:
        logger.warning(
            "Permission denied: subject=%s permission=%s resource=%s/%s",
            subject,
            permission,
            resource_type,
            resource_id,
        )
        raise HTTPException(status_code=403, detail="Permission denied")
