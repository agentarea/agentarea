"""OSS permission service — allows all operations."""

from .permission import PermissionService


class WorkspaceScopedPermissionService(PermissionService):
    """Workspace-scoped permission checks. No external dependencies.

    In OSS mode, all operations are allowed. Workspace isolation
    is enforced at the repository layer via WorkspaceScopedMixin.
    """

    async def check(
        self,
        user_id: str,
        permission: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        return True
