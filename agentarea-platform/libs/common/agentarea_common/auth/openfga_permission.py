"""OpenFGA-backed permission service."""

import logging

from ..rebac.openfga_client import OpenFGAClient
from .permission import PermissionService

logger = logging.getLogger(__name__)

# Resource types intentionally NOT governed by the relationship graph. They are
# scoped by the database/workspace layer only, so a graph check would deny a
# legitimate owner that has no tuple. Anything NOT listed here is treated as a
# ``resource:<id>`` object and fails CLOSED when it has no tuples.
_UNGOVERNED_RESOURCE_TYPES = {"model_instance", "model"}

# Generic verb -> independent permission bit on the ``resource`` model. The bits
# do NOT imply each other (no roll-up): a creator is granted all three at create.
_BIT_BY_PERMISSION = {
    "view": "can_read",
    "use": "can_read",
    "read": "can_read",
    "execute": "can_read",
    "operate": "can_read",
    "connect": "can_read",
    "edit": "can_write",
    "write": "can_write",
    "update": "can_write",
    "configure": "can_write",
    "manage": "can_manage",
    "own": "can_manage",
    "delete": "can_manage",
}


class OpenFGAPermissionService(PermissionService):
    """Resolve permissions via OpenFGA ``resource`` tuple checks.

    Agents, skills, MCP servers, and clients are all ``resource:<id>`` objects;
    their "kind" lives in the DB, not the graph. The generic verb maps onto one
    of the three independent permission bits (``can_read`` / ``can_write`` /
    ``can_manage``).
    """

    def __init__(self, openfga_client: OpenFGAClient) -> None:
        self._openfga = openfga_client

    async def check(
        self,
        user_id: str,
        permission: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        if resource_type in _UNGOVERNED_RESOURCE_TYPES:
            return True

        relation = _BIT_BY_PERMISSION.get(permission)
        if relation is None:
            logger.warning(
                "No resource permission mapping for %s.%s; denying", resource_type, permission
            )
            return False
        # Fail CLOSED: on an OpenFGA outage we raise rather than coerce the check
        # to allow OR deny. The caller (require_permission) surfaces the failure.
        result = await self._openfga.check(
            namespace="resource",
            object=resource_id,
            relation=relation,
            subject_id=f"User:{user_id}",
        )
        return result.allowed
