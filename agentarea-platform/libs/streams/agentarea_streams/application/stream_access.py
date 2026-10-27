"""Who may read a stream: the one question every reader of it asks.

Today the answer is the authorization graph's ``read`` on the stream, which a
workspace member has through the workspace root. Stream-level ReBAC (who sees
mail and chat streams) changes this module only.
"""

from uuid import UUID

from agentarea_common.auth.permission import GraphCaller, PermissionService
from agentarea_common.auth.resource_visibility import readable_resource_ids


class StreamReaders:
    def __init__(self, permissions: PermissionService):
        self._permissions = permissions

    async def may_read(self, caller: GraphCaller, stream_id: UUID) -> bool:
        return await self._permissions.check(caller.graph_subject, "read", "stream", str(stream_id))

    async def readable(self, caller: GraphCaller) -> set[str]:
        """Ids of every stream (and other resource) the caller may read."""
        return await readable_resource_ids(caller)
