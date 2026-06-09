"""Keto-backed permission service.

Maps the generic ``check(user_id, permission, resource_type, resource_id)``
contract onto Keto namespace/relation checks. Subjects are users
(``User:<user_id>``). Fails closed: if Keto is unreachable the check denies.
"""

import logging

from ..rebac.keto_client import KetoClient, KetoError
from .permission import PermissionService

logger = logging.getLogger(__name__)

# resource_type (generic) -> Keto namespace
_NAMESPACE_BY_RESOURCE = {
    "skill": "Skill",
    "skill_collection": "SkillCollection",
    "mcp_server": "MCPServer",
    "agent": "Agent",
}

# (namespace, generic permission) -> Keto relation/permission name.
_RELATION_BY_PERMISSION: dict[str, dict[str, str]] = {
    "Skill": {
        "view": "use",
        "use": "use",
        "execute": "use",
        "edit": "configure",
        "configure": "configure",
        "manage": "manage",
        "delete": "manage",
    },
    "SkillCollection": {
        "view": "use",
        "use": "use",
        "edit": "configure",
        "configure": "configure",
        "manage": "manage",
        "delete": "manage",
    },
    "MCPServer": {
        "view": "connect",
        "use": "connect",
        "connect": "connect",
        "execute": "connect",
        "manage": "manage",
        "edit": "manage",
        "delete": "manage",
    },
    "Agent": {
        "view": "operate",
        "use": "operate",
        "execute": "operate",
        "operate": "operate",
        "manage": "own",
        "edit": "own",
        "delete": "own",
    },
}


class KetoPermissionService(PermissionService):
    """Resolve permissions via Ory Keto relation-tuple checks."""

    def __init__(self, keto_client: KetoClient) -> None:
        self._keto = keto_client

    async def check(
        self,
        user_id: str,
        permission: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        namespace = _NAMESPACE_BY_RESOURCE.get(resource_type)
        if namespace is None:
            # Unknown resource type -> not governed by the rebac graph; allow.
            return True
        relation = _RELATION_BY_PERMISSION.get(namespace, {}).get(permission)
        if relation is None:
            logger.warning("No Keto relation mapping for %s.%s; denying", resource_type, permission)
            return False
        try:
            result = await self._keto.check(
                namespace=namespace,
                object=resource_id,
                relation=relation,
                subject_id=f"User:{user_id}",
            )
        except KetoError:
            logger.exception(
                "Keto check failed (user=%s perm=%s res=%s/%s); denying",
                user_id,
                permission,
                resource_type,
                resource_id,
            )
            return False
        return result.allowed
