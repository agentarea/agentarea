"""Reusable mock activities and helpers for workflow integration tests."""

import json
from typing import Any
from uuid import uuid4

from temporalio import activity

from agentarea_execution.models import (
    AgentConfigRequest,
    ArtifactValidationRequest,
    ArtifactValidationResult,
    LLMCallRequest,
    MCPToolRequest,
    ResolveModelRequest,
    ToolDiscoveryRequest,
    UpdateTaskStatusRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)

# ---------------------------------------------------------------------------
# LLM response builders
# ---------------------------------------------------------------------------


def llm_response_text(content: str = "Hello!", cost: float = 0.001) -> dict[str, Any]:
    """Plain text response, no tool calls."""
    return {
        "content": content,
        "role": "assistant",
        "tool_calls": [],
        "finish_reason": "stop",
        "cost": cost,
        "usage": {"prompt_tokens": 10, "completion_tokens": 15, "total_tokens": 25},
    }


def llm_response_completion(result: str = "Task completed") -> dict[str, Any]:
    """LLM calls the completion tool -> triggers task_complete."""
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": f"call_{uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": "completion",
                    "arguments": json.dumps({"result": result}),
                },
            }
        ],
        "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
    }


def llm_response_tool_call(tool_name: str = "search", args: dict | None = None) -> dict[str, Any]:
    """LLM calls a regular tool -> triggers another iteration."""
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "id": f"call_{uuid4().hex[:8]}",
                "type": "function",
                "function": {
                    "name": tool_name,
                    "arguments": json.dumps(args or {"query": "test"}),
                },
            }
        ],
        "finish_reason": "tool_calls",
        "cost": 0.001,
        "usage": {"prompt_tokens": 50, "completion_tokens": 30, "total_tokens": 80},
    }


# ---------------------------------------------------------------------------
# Sequenced LLM mock activity
# ---------------------------------------------------------------------------


def make_sequenced_llm_activity(responses: list[dict[str, Any]]):
    """Create a call_llm_activity that returns responses in sequence.

    After exhausting the list, repeats the last response.
    """
    call_count = {"n": 0}

    @activity.defn(name="call_llm_activity")
    async def sequenced_call_llm(request: LLMCallRequest) -> dict[str, Any]:
        idx = min(call_count["n"], len(responses) - 1)
        call_count["n"] += 1
        return responses[idx]

    return sequenced_call_llm


# ---------------------------------------------------------------------------
# Event capture
# ---------------------------------------------------------------------------


class EventCapture:
    """Captures published events in order for assertions."""

    def __init__(self):
        self.events: list[dict[str, Any]] = []

    @property
    def event_types(self) -> list[str]:
        return [e["event_type"] for e in self.events]

    def make_activity(self):
        """Create a publish_workflow_events_activity that captures events."""
        capture = self

        @activity.defn(name="publish_workflow_events_activity")
        async def mock_publish_events(
            request: WorkflowEventsRequest,
        ) -> WorkflowEventsResult:
            for ej in request.events_json:
                if not ej or not ej.strip():
                    continue
                data = json.loads(ej)
                capture.events.append(data)
            return WorkflowEventsResult(success=True, events_published=len(request.events_json))

        return mock_publish_events


# ---------------------------------------------------------------------------
# Standard boilerplate mock activities
# ---------------------------------------------------------------------------


@activity.defn(name="build_agent_config_activity")
async def mock_build_agent_config(request: AgentConfigRequest) -> dict[str, Any]:
    return {
        "id": str(request.agent_id),
        "name": "Test Agent",
        "model_id": "gpt-4o-mini",
        "instruction": "You are a helpful assistant.",
        "tools_config": {"mcp_servers": []},
        "events_config": {},
        "planning": False,
    }


@activity.defn(name="discover_available_tools_activity")
async def mock_discover_tools(request: ToolDiscoveryRequest) -> dict[str, Any]:
    return {"tools": [], "context_strategy": "STATIC"}


@activity.defn(name="resolve_model_activity")
async def mock_resolve_model(request: ResolveModelRequest) -> dict[str, Any]:
    return {
        "model_id": request.model_id,
        "provider_type": "openai",
        "model_name": "gpt-4o-mini",
        "api_key_secret": None,
        "endpoint_url": None,
        "context_window": 128000,
        "display_name": "GPT-4o Mini",
        "provider_display_name": "OpenAI",
        "resolved_at": "2026-01-01T00:00:00+00:00",
    }


@activity.defn(name="execute_mcp_tool_activity")
async def mock_execute_mcp_tool(request: MCPToolRequest) -> dict[str, Any]:
    return {"success": True, "result": "Mock result", "tool_name": request.tool_name}


@activity.defn(name="update_task_status_activity")
async def mock_update_task_status(request: UpdateTaskStatusRequest) -> bool:
    return True


@activity.defn(name="validate_artifacts_activity")
async def mock_validate_artifacts(
    request: ArtifactValidationRequest,
) -> ArtifactValidationResult:
    return ArtifactValidationResult(state="no_artifacts", generation=0)
