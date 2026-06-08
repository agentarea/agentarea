"""OSS authorization service — pure policy, no infrastructure access."""

from .authorization import AuthorizationService
from .context import UserContext


class SimpleAuthorizationService(AuthorizationService):
    """OSS implementation of workspace access control.

    Pure policy: own workspace only. Built-in/official content is no longer made
    visible by injecting a magic 'platform' workspace here — it is globally
    readable by provenance (``source == 'official'``) in the repository layer, or
    lives in the global registry catalog.

    Workspace memberships (added by accepting invitations) are resolved by
    the request-scoped dependency in ``auth.dependencies``, not here, so
    this service stays free of infrastructure dependencies and can run as
    a singleton without leaking SQL sessions across requests.

    Enterprise replaces this with ReBAC-based resolution.
    """

    async def get_accessible_workspaces(self, user_context: UserContext) -> list[str]:
        return [user_context.workspace_id]

    async def can_write_workspace(self, user_context: UserContext, workspace_id: str) -> bool:
        return workspace_id == user_context.workspace_id
