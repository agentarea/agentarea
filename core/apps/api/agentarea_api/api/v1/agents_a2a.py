"""A2A (Agent-to-Agent) protocol endpoints for AgentArea.

This module implements the A2A protocol for inter-agent communication.
The A2A protocol is a JSON-RPC based protocol that allows agents to:
- Send messages to other agents
- Submit tasks for execution
- Query task status
- Cancel tasks

Key endpoints:
- POST /agents/{agent_id}/a2a/rpc - JSON-RPC endpoint for A2A protocol
- GET /agents/{agent_id}/a2a/well-known - Agent discovery endpoint
"""

import json
import logging
from typing import Any
from uuid import UUID, uuid4

from agentarea_agents.application.agent_service import AgentService
from agentarea_api.api.deps.services import get_agent_service, get_task_service
from agentarea_api.api.v1.a2a_auth import (
    A2AAuthContext,
    allow_public_access,
    require_a2a_execute_auth,
)
from agentarea_common.utils.types import (
    AgentCapabilities,
    AgentCard,
    CancelTaskResponse,
    GetTaskResponse,
    JSONRPCRequest,
    JSONRPCResponse,
    Message,
    MessageSendParams,
    TextPart,
)
from agentarea_common.utils.types import (
    AuthenticatedExtendedCardResponse as AgentAuthenticatedExtendedCardResponse,
)
from agentarea_common.utils.types import (
    MessageSendResponse as SendMessageResponse,
)
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.task_service import TaskService
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/a2a")

def _extract_text_from_parts(parts):
    return "".join(part.get("text", "") for part in parts if isinstance(part, dict) and "text" in part)

def convert_a2a_message_to_task(message_params: MessageSendParams, agent_id: UUID, task_id: str = None) -> SimpleTask:
    message_content = ""
    if message_params.message and message_params.message.parts:
        for part in message_params.message.parts:
            if hasattr(part, 'text'):
                message_content += part.text
    return SimpleTask(
        id=UUID(task_id) if task_id else uuid4(),
        title="A2A Message Task",
        description="Task created from A2A message",
        query=message_content,
        user_id="a2a_user",
        agent_id=agent_id,
        status="submitted",
        task_parameters={}
    )

def convert_task_to_a2a_response(task: SimpleTask) -> dict[str, Any]:
    return {
        "id": str(task.id),
        "status": task.status,
        "result": task.result,
        "error": task.error_message,
        "created_at": task.created_at.isoformat() if task.created_at else None,
        "updated_at": task.updated_at.isoformat() if task.updated_at else None,
    }

async def handle_task_send(request_id, params, task_service, agent_id):
    try:
        message_send_params = MessageSendParams(**params)
        task = convert_a2a_message_to_task(message_send_params, agent_id)
        created_task = await task_service.submit_task(task)
        return SendMessageResponse(
            jsonrpc="2.0",
            id=request_id,
            result={
                "id": str(created_task.id),
                "status": created_task.status,
                "message": "Task submitted successfully"
            }
        )
    except Exception as e:
        logger.error(f"Error in handle_task_send: {e}")
        return SendMessageResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Task submission failed: {e!s}"}
        )

async def handle_message_send(request_id, params, task_service, agent_id):
    try:
        message_data = params.get("message", {})
        text_content = _extract_text_from_parts(message_data.get("parts", []))
        message = Message(role="user", parts=[TextPart(text=text_content)])
        message_params = MessageSendParams(message=message)
        task = convert_a2a_message_to_task(message_params, agent_id)
        created_task = await task_service.submit_task(task)
        return SendMessageResponse(
            jsonrpc="2.0",
            id=request_id,
            result={
                "id": str(created_task.id),
                "status": created_task.status,
                "message": "Task submitted successfully"
            }
        )
    except Exception as e:
        logger.error(f"Error in handle_message_send: {e}")
        return SendMessageResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Message send failed: {e!s}"}
        )

async def handle_message_stream_sse(request, request_id, params, task_service, agent_id):
    try:
        message_data = params.get("message", {})
        text_content = _extract_text_from_parts(message_data.get("parts", []))
        task = SimpleTask(
            id=UUID(params.get("id", str(uuid4()))),
            title="A2A Stream Task",
            description="Task created from A2A stream message",
            query=text_content,
            user_id="a2a_user",
            agent_id=agent_id,
            status="submitted",
            task_parameters={}
        )
        created_task = await task_service.submit_task(task)
        async def event_stream():
            yield f"data: {json.dumps({'event': 'task_created', 'task_id': str(created_task.id)})}\n\n"
            yield f"data: {json.dumps({'event': 'task_completed', 'task_id': str(created_task.id), 'result': created_task.result})}\n\n"
            yield "data: [DONE]\n\n"
        return StreamingResponse(
            event_stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "Access-Control-Allow-Origin": "*",
            }
        )
    except Exception as e:
        logger.error(f"Error in handle_message_stream_sse: {e}")
        async def error_stream():
            yield f"data: {json.dumps({'event': 'error', 'message': str(e)})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

async def handle_task_get(request_id, params, task_service):
    try:
        task_id = UUID(params.get("id", ""))
        task = await task_service.get_task(task_id)
        if not task:
            return GetTaskResponse(
                jsonrpc="2.0",
                id=request_id,
                error={"code": -32602, "message": f"Task not found: {task_id}"}
            )
        return GetTaskResponse(
            jsonrpc="2.0",
            id=request_id,
            result=convert_task_to_a2a_response(task)
        )
    except Exception as e:
        logger.error(f"Error in handle_task_get: {e}")
        return GetTaskResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Task get failed: {e!s}"}
        )

async def handle_task_cancel(request_id, params, task_service):
    try:
        task_id = UUID(params.get("id", ""))
        success = await task_service.cancel_task(task_id)
        return CancelTaskResponse(
            jsonrpc="2.0",
            id=request_id,
            result={"success": success, "message": "Task cancelled" if success else "Task not found or already completed"}
        )
    except Exception as e:
        logger.error(f"Error in handle_task_cancel: {e}")
        return CancelTaskResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Task cancel failed: {e!s}"}
        )

async def handle_agent_card(request_id, params, agent_service, agent_id, base_url):
    try:
        agent = await agent_service.get(agent_id)
        if not agent:
            return AgentAuthenticatedExtendedCardResponse(
                jsonrpc="2.0",
                id=request_id,
                error={"code": -32602, "message": f"Agent not found: {agent_id}"}
            )
        from agentarea_common.utils.types import AgentProvider, AgentSkill
        agent_card = AgentCard(
            name=agent.name,
            description=agent.description or "",
            url=f"{base_url}/api/v1/agents/{agent_id}/a2a/rpc",
            version="1.0.0",
            provider=AgentProvider(organization="AgentArea"),
            capabilities=AgentCapabilities(
                streaming=True,
                push_notifications=False,
                state_transition_history=True,
            ),
            skills=[
                AgentSkill(
                    id="text-processing",
                    name="Text Processing",
                    description=f"Process and respond to text messages using {agent.name}",
                    input_modes=["text"],
                    output_modes=["text"],
                )
            ],
        )
        return AgentAuthenticatedExtendedCardResponse(
            jsonrpc="2.0",
            id=request_id,
            result=agent_card
        )
    except Exception as e:
        logger.error(f"Error in handle_agent_card: {e}")
        return AgentAuthenticatedExtendedCardResponse(
            jsonrpc="2.0",
            id=request_id,
            error={"code": -32603, "message": f"Agent card failed: {e!s}"}
        )

async def _dispatch_rpc_method(
    method: str,
    *,
    request_id,
    params,
    request,
    task_service,
    agent_service,
    agent_id,
):
    base_url = f"{request.url.scheme}://{request.url.netloc}" if request else None
    handlers = {
        "tasks/send": lambda: handle_task_send(request_id, params, task_service, agent_id),
        "message/send": lambda: handle_message_send(request_id, params, task_service, agent_id),
        "message/stream": lambda: handle_message_stream_sse(request, request_id, params, task_service, agent_id),
        "tasks/get": lambda: handle_task_get(request_id, params, task_service),
        "tasks/cancel": lambda: handle_task_cancel(request_id, params, task_service),
        "agent/authenticatedExtendedCard": lambda: handle_agent_card(request_id, params, agent_service, agent_id, base_url),
    }
    handler = handlers.get(method)
    if handler:
        return await handler()
    return JSONRPCResponse(
        jsonrpc="2.0",
        id=request_id,
        error={"code": -32601, "message": f"Method not found: {method}"},
    )

@router.post("/rpc")
async def handle_agent_jsonrpc(
    agent_id: UUID,
    request: Request,
    task_service: TaskService = Depends(get_task_service),
    auth_context: A2AAuthContext = Depends(require_a2a_execute_auth),
    agent_service: AgentService = Depends(get_agent_service),
) -> JSONRPCResponse:
    try:
        body = await request.body()
        request_data = json.loads(body)
        rpc_request = JSONRPCRequest(**request_data)
        method = rpc_request.method
        params = rpc_request.params or {}
        request_id = rpc_request.id
        logger.info(f"A2A RPC call: {method} for agent {agent_id}")
        return await _dispatch_rpc_method(
            method,
            request_id=request_id,
            params=params,
            request=request,
            task_service=task_service,
            agent_service=agent_service,
            agent_id=agent_id,
        )
    except json.JSONDecodeError:
        return JSONRPCResponse(
            jsonrpc="2.0",
            id=None,
            error={"code": -32700, "message": "Parse error"},
        )
    except Exception as e:
        logger.error(f"A2A RPC error: {e}")
        return JSONRPCResponse(
            jsonrpc="2.0",
            id=locals().get("request_id", None),
            error={"code": -32603, "message": f"Internal error: {e!s}"},
        )

@router.get("/well-known")
async def get_agent_well_known(
    agent_id: UUID,
    auth_context: A2AAuthContext = Depends(allow_public_access),
    agent_service: AgentService = Depends(get_agent_service),
) -> AgentCard:
    try:
        agent = await agent_service.get(agent_id)
        if not agent:
            raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
        from agentarea_common.utils.types import AgentProvider, AgentSkill
        agent_card = AgentCard(
            name=agent.name,
            description=agent.description or "",
            url=f"/api/v1/agents/{agent_id}/a2a/rpc",
            version="1.0.0",
            provider=AgentProvider(organization="AgentArea"),
            capabilities=AgentCapabilities(
                streaming=True,
                push_notifications=False,
                state_transition_history=True,
            ),
            skills=[
                AgentSkill(
                    id="text-processing",
                    name="Text Processing",
                    description=f"Process and respond to text messages using {agent.name}",
                    input_modes=["text"],
                    output_modes=["text"],
                )
            ],
        )
        return agent_card
    except Exception as e:
        logger.error(f"Error in get_agent_well_known: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get agent info: {e!s}")
