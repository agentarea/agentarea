"""Creating a trigger, shared by the trigger routes, agent creation and the triggers toolset."""

from uuid import UUID

from agentarea_common.auth.context import UserContext
from agentarea_common.auth.permission import require_permission
from agentarea_triggers.domain.models import Trigger
from agentarea_triggers.schemas.dto import TriggerSpec
from agentarea_triggers.trigger_service import TriggerService


async def require_stream_readable(stream_id: UUID | None, user_id: str) -> None:
    """Refuse a stream trigger on a stream its creator may not read (403).

    The trigger hands every event of the stream to the agent as task input, so
    subscribing is reading.
    """
    if stream_id is not None:
        await require_permission("read", "stream", str(stream_id), user_id)


async def create_trigger_from_spec(
    spec: TriggerSpec,
    *,
    agent_id: UUID,
    user_context: UserContext,
    trigger_service: TriggerService,
) -> Trigger:
    """Create one trigger for ``agent_id``.

    A spec with ``enabled=False`` is created inactive with its schedule paused,
    so it never fires before its owner switches it on.
    """
    if spec.trigger_type == "stream":
        await require_stream_readable(spec.stream_id, user_context.user_id)
    return await trigger_service.create_trigger(
        spec.to_domain_for(
            agent_id, created_by=user_context.user_id, workspace_id=user_context.workspace_id
        )
    )
