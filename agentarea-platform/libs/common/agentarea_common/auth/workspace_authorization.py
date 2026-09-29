"""Workspace-scoped authorization service — pure policy, no infrastructure access."""

from .authorization import AuthorizationService
from .context import UserContext, UserPrincipal


class WorkspaceScopedAuthorizationService(AuthorizationService):
    """Workspace-scoped access control (the open-core default).

    Pure policy: owned and joined workspaces only, both resolved by the
    request-scoped dependency in ``auth.dependencies``, so this grants nothing
    on top of them. Built-in/official content is not made visible by injecting a
    magic 'platform' workspace here — it lives in the global registry catalog
    and is read globally by the catalog repositories.

    Keeping infrastructure out of this service lets it run as a singleton
    without leaking SQL sessions across requests.

    Enterprise replaces this with ReBAC-based resolution.
    """

    async def get_accessible_workspaces(self, principal: UserPrincipal) -> list[str]:
        return []

    async def can_write_workspace(self, user_context: UserContext, workspace_id: str) -> bool:
        return workspace_id == user_context.workspace_id
