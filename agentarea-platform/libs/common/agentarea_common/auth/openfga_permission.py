"""OpenFGA-backed permission service."""

import logging

from ..rebac.openfga_client import OpenFGAClient, OpenFGAError
from .permission import PermissionService

logger = logging.getLogger(__name__)

_NAMESPACE_BY_RESOURCE = {
    "skill": "Skill",
    "skill_collection": "SkillCollection",
    "mcp_server": "MCPServer",
    "agent": "Agent",
}

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


class OpenFGAPermissionService(PermissionService):
    """Resolve permissions via OpenFGA tuple checks."""

    def __init__(self, openfga_client: OpenFGAClient) -> None:
        self._openfga = openfga_client

    async def check(
        self,
        user_id: str,
        permission: str,
        resource_type: str,
        resource_id: str,
    ) -> bool:
        namespace = _NAMESPACE_BY_RESOURCE.get(resource_type)
        if namespace is None:
            return True
        relation = _RELATION_BY_PERMISSION.get(namespace, {}).get(permission)
        if relation is None:
            logger.warning(
                "No OpenFGA relation mapping for %s.%s; denying", resource_type, permission
            )
            return False
        try:
            result = await self._openfga.check(
                namespace=namespace,
                object=resource_id,
                relation=relation,
                subject_id=f"User:{user_id}",
            )
        except OpenFGAError:
            logger.exception(
                "OpenFGA check failed (user=%s perm=%s res=%s/%s); denying",
                user_id,
                permission,
                resource_type,
                resource_id,
            )
            return False
        return result.allowed
