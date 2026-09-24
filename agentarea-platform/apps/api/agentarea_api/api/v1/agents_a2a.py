"""A2A (Agent-to-Agent) protocol endpoint for one agent.

``POST /agents/{agent_id}/a2a/rpc`` authenticates and authorizes the caller
through the shared edge policy, then hands the request to the official SDK's
JSON-RPC dispatcher, which owns the protocol. The domain side lives in
:mod:`agentarea_api.api.v1.a2a_request_handler`.
"""

from uuid import UUID

from a2a.server.routes.jsonrpc_dispatcher import JsonRpcDispatcher
from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import (
    get_agent_service,
    get_secret_manager,
    get_task_service,
)
from agentarea_api.api.v1.a2a_auth import A2AAuthContext, require_a2a_execute_auth
from agentarea_api.api.v1.a2a_card import get_base_url
from agentarea_api.api.v1.a2a_request_handler import (
    A2ACallScope,
    AgentAreaCallContextBuilder,
    AgentAreaRequestHandler,
)
from agentarea_api.api.v1.agents_well_known import public_agent_card_response
from agentarea_api.api.v1.task_event_feed import open_task_event_feed
from agentarea_common.auth.route_authz import unrestricted
from agentarea_common.config.database import get_read_db_session
from agentarea_common.infrastructure.secret_manager import BaseSecretManager
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/a2a")

_context_builder = AgentAreaCallContextBuilder()


@router.post(
    "/rpc",
    response_model=None,
    dependencies=[unrestricted("A2A JSON-RPC surface; the agent card and task auth govern it")],
)
async def handle_agent_jsonrpc(
    agent_id: UUID,
    request: Request,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    task_service: TaskService = Depends(get_task_service),
    agent_service: AgentService = Depends(get_agent_service),
    secret_manager: BaseSecretManager = Depends(get_secret_manager),
) -> Response:
    """Serve one A2A JSON-RPC call (plain JSON, or SSE for the streaming methods)."""
    request.state.a2a_scope = A2ACallScope(
        agent_id=agent_id, auth=auth_context, base_url=get_base_url(request)
    )
    handler = AgentAreaRequestHandler(
        task_service=task_service,
        agent_service=agent_service,
        secret_manager=secret_manager,
        event_feed=open_task_event_feed,
    )
    dispatcher = JsonRpcDispatcher(handler, context_builder=_context_builder)
    return await dispatcher.handle_requests(request)


@router.get(
    "/well-known",
    response_model=None,
    dependencies=[
        unrestricted("agent discovery document, the contract an A2A peer reads before talking")
    ],
)
async def get_agent_well_known(
    agent_id: UUID,
    request: Request,
    db_session: AsyncSession = Depends(get_read_db_session),
) -> Response:
    """The agent card, also served at ``.well-known/agent-card.json``."""
    return await public_agent_card_response(agent_id, request, db_session)
