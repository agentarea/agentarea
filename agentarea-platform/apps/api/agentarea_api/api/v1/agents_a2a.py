"""A2A (Agent-to-Agent) protocol endpoint for one agent.

Every agent is served on its own host, ``A2A_AGENT_URL`` with the agent id as
the first label: ``POST /`` is its JSON-RPC endpoint and
``GET /.well-known/agent-card.json`` its card, as RFC 8615 places it. The
same agent also answers under the API host at ``/v1/agents/{agent_id}/a2a/rpc``.

Either way the caller is authenticated and authorized through the shared edge
policy, then the request goes to the official SDK's JSON-RPC dispatcher, which
owns the protocol. The domain side lives in
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
from agentarea_api.api.rate_limit import limit_a2a_rpc
from agentarea_api.api.v1.a2a_auth import (
    A2AAuthContext,
    require_a2a_execute_auth,
    require_a2a_read_auth,
)
from agentarea_api.api.v1.a2a_card import agent_host_rpc_url, agent_rpc_url
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
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.routing import Host
from starlette.types import Receive, Scope, Send

router = APIRouter(prefix="/a2a")

_context_builder = AgentAreaCallContextBuilder()


async def _dispatch(
    request: Request,
    *,
    agent_id: UUID,
    rpc_url: str,
    auth_context: A2AAuthContext,
    task_service: TaskService,
    agent_service: AgentService,
    secret_manager: BaseSecretManager,
) -> Response:
    request.state.a2a_scope = A2ACallScope(agent_id=agent_id, auth=auth_context, rpc_url=rpc_url)
    handler = AgentAreaRequestHandler(
        task_service=task_service,
        agent_service=agent_service,
        secret_manager=secret_manager,
        event_feed=open_task_event_feed,
    )
    dispatcher = JsonRpcDispatcher(handler, context_builder=_context_builder)
    return await dispatcher.handle_requests(request)


@router.post(
    "/rpc",
    response_model=None,
    dependencies=[
        unrestricted("A2A JSON-RPC surface; the agent card and task auth govern it"),
        Depends(limit_a2a_rpc),
    ],
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
    return await _dispatch(
        request,
        agent_id=agent_id,
        rpc_url=agent_rpc_url(agent_id),
        auth_context=auth_context,
        task_service=task_service,
        agent_service=agent_service,
        secret_manager=secret_manager,
    )


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
    return await public_agent_card_response(agent_id, db_session, rpc_url=agent_rpc_url(agent_id))


agent_host_router = APIRouter(dependencies=[Depends(require_a2a_read_auth)])


@agent_host_router.post(
    "/",
    response_model=None,
    dependencies=[
        unrestricted("A2A JSON-RPC surface; the agent card and task auth govern it"),
        Depends(limit_a2a_rpc),
    ],
)
async def handle_agent_host_jsonrpc(
    agent_id: UUID,
    request: Request,
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    task_service: TaskService = Depends(get_task_service),
    agent_service: AgentService = Depends(get_agent_service),
    secret_manager: BaseSecretManager = Depends(get_secret_manager),
) -> Response:
    """Serve one A2A JSON-RPC call at the root of the agent's own host."""
    return await _dispatch(
        request,
        agent_id=agent_id,
        rpc_url=agent_host_rpc_url(agent_id),
        auth_context=auth_context,
        task_service=task_service,
        agent_service=agent_service,
        secret_manager=secret_manager,
    )


agent_card_host_router = APIRouter()


@agent_card_host_router.get(
    "/.well-known/agent-card.json",
    response_model=None,
    dependencies=[
        unrestricted("agent discovery document, the contract an A2A peer reads before talking")
    ],
)
async def get_agent_host_card(
    agent_id: UUID,
    request: Request,
    db_session: AsyncSession = Depends(get_read_db_session),
) -> Response:
    """The agent card at the well-known path of the agent's own host."""
    return await public_agent_card_response(
        agent_id, db_session, rpc_url=agent_host_rpc_url(agent_id)
    )


class _AgentHost:
    """Prefix the path with the agent id the host named.

    Routes then declare ``agent_id`` as a path parameter, as every other A2A
    route does; FastAPI reads a parameter missing from the path as a query one.
    """

    def __init__(self, routes: APIRouter):
        self._routes = routes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        path = f"/{scope['path_params']['agent_id']}{scope['path']}"
        await self._routes({**scope, "path": path, "raw_path": path.encode()}, receive, send)


def agent_host_route(host_pattern: str, app: FastAPI) -> Host:
    """Serve the agent named by the host's first label; any other path is 404.

    ``host_pattern`` is the host part of ``A2A_AGENT_URL``, e.g.
    ``{agent_id}.a2a.example.com``. The card is public, the RPC endpoint
    authenticates like every other A2A route. ``app`` provides dependency
    overrides, which a router mounted outside ``include_router`` would not see.
    """
    routes = APIRouter(dependency_overrides_provider=app)
    routes.include_router(agent_card_host_router, prefix="/{agent_id}")
    routes.include_router(agent_host_router, prefix="/{agent_id}")
    # Only a UUID label is an agent, so no other host can be captured by mistake.
    pattern = host_pattern.replace("{agent_id}", "{agent_id:uuid}")
    return Host(pattern, app=_AgentHost(routes))
