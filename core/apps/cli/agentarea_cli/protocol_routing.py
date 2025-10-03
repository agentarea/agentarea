"""Protocol routing utilities for CLI commands."""

import json
import uuid
from typing import TYPE_CHECKING, Any

import click
import httpx

if TYPE_CHECKING:
    from agentarea_cli.client import AgentAreaClient


class ProtocolRouter:
    """Handles routing between internal API and A2A protocol."""

    def __init__(self, client: "AgentAreaClient"):
        self.client = client

    @staticmethod
    def normalize_event(event_data: dict, protocol: str) -> dict:
        """Normalize event data between internal and A2A formats."""
        if protocol == "a2a":
            # A2A events use 'event' field, convert to internal 'event_type'
            if "event" in event_data and "event_type" not in event_data:
                event_data["event_type"] = event_data["event"]
                # Add workflow. prefix if not present for internal compatibility
                if not event_data["event_type"].startswith("workflow."):
                    if event_data["event_type"] not in ["connected", "task_created"]:
                        event_data["event_type"] = f"workflow.{event_data['event_type']}"
        else:
            # Internal events use 'event_type', convert to A2A 'event' if needed
            if "event_type" in event_data and "event" not in event_data:
                event_type = event_data["event_type"]
                # Strip workflow. prefix for A2A compatibility
                if event_type.startswith("workflow."):
                    event_type = event_type[9:]
                event_data["event"] = event_type

        return event_data

    @staticmethod
    def _extract_agent_name(data_payload: dict, current: str | None) -> str | None:
        # Prefer explicit agent_name
        name = data_payload.get("agent_name")
        if name:
            return name
        # Check nested agent object
        agent_obj = data_payload.get("agent") or {}
        if isinstance(agent_obj, dict):
            name = agent_obj.get("name") or agent_obj.get("title")
            if name:
                return name
        # Fallback to current value
        return current

    @staticmethod
    def extract_chunk_content(event_data: dict) -> str:
        """Extract chunk content from event data, checking multiple common locations."""
        # 1) Check original_data.chunk first (filtered internal streams)
        original_data = event_data.get("original_data", {})
        chunk = original_data.get("chunk", "")
        if chunk:
            return chunk

        # 2) Check data.chunk (direct internal streams)
        data_payload = event_data.get("data", {})
        if isinstance(data_payload, str) and data_payload:
            return data_payload
        chunk = data_payload.get("chunk", "") if isinstance(data_payload, dict) else ""
        if chunk:
            return chunk

        # 3) Common A2A deltas
        # e.g. data: { delta: { text: "..." } }
        delta = (
            event_data.get("delta")
            or (data_payload.get("delta") if isinstance(data_payload, dict) else None)
            or {}
        )
        if isinstance(delta, dict):
            text = delta.get("text") or delta.get("content") or delta.get("value")
            if isinstance(text, str) and text:
                return text

        # 4) Sometimes plain text or content fields are streamed
        text = event_data.get("text") or (
            data_payload.get("text") if isinstance(data_payload, dict) else None
        )
        if isinstance(text, str) and text:
            return text
        content = event_data.get("content") or (
            data_payload.get("content") if isinstance(data_payload, dict) else None
        )
        if isinstance(content, str) and content:
            return content
        # If content is a list of blocks, try to join text
        if isinstance(content, list):
            parts: list[str] = []
            for block in content:
                if isinstance(block, dict):
                    val = block.get("text") or block.get("content") or block.get("value")
                    if isinstance(val, str):
                        parts.append(val)
            if parts:
                return "".join(parts)

        return ""

    async def send_a2a_message(
        self,
        agent_id: str,
        message: str,
        parameters: dict | None = None,
        user_id: str = "cli_user",
        stream: bool = False,
        output_format: str = "text",
        requires_human_approval: bool = False,
    ) -> Any:
        """Send message via A2A protocol."""
        base_url = self.client.base_url
        headers = self.client._get_headers()
        url = f"{base_url}/v1/agents/{agent_id}/a2a/rpc"

        # Use streaming method if requested
        method = "message/stream" if stream else "message/send"

        # Include parameters in message if provided (kept for backward compatibility)
        message_text = message
        if parameters:
            message_text += f"\nParameters: {json.dumps(parameters)}"

        # Prepare metadata for JSON-RPC params
        metadata = {"requires_human_approval": requires_human_approval}
        if parameters:
            # Also include provided parameters inside metadata for server-side use
            metadata.update(parameters)

        # Prepare JSON-RPC request
        request_data = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": {
                "message": {"role": "user", "parts": [{"text": message_text}]},
                "metadata": metadata,
            },
        }

        if stream:
            # Return streaming response
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream(
                    "POST", url, json=request_data, headers=headers
                ) as response:
                    if response.status_code != 200:
                        error_text = await response.aread()
                        raise Exception(f"HTTP {response.status_code}: {error_text.decode()}")

                    await self._process_a2a_stream(response, output_format)
        else:
            async with httpx.AsyncClient() as client:
                response = await client.post(url, json=request_data, headers=headers)
                if response.status_code == 200:
                    response_data = response.json()
                    if "result" in response_data:
                        if output_format == "json":
                            click.echo(json.dumps(response_data["result"], indent=2))
                        else:
                            content = response_data["result"].get("content", "")
                            if content:
                                click.echo(content)
                        return response_data["result"]
                    elif "error" in response_data:
                        error = response_data["error"]
                        raise Exception(f"A2A Error {error.get('code')}: {error.get('message')}")
                else:
                    error_text = response.text
                    raise Exception(f"HTTP {response.status_code}: {error_text}")

    async def stream_task_create_a2a(
        self,
        agent_id: str,
        description: str,
        parameters: dict | None = None,
        user_id: str = "cli_user",
        timeout: int = 300,
        output_format: str = "text",
        requires_human_approval: bool = False,
    ):
        """Stream task creation via A2A protocol using message/stream."""
        # Use message/stream for creating and streaming task
        await self.send_a2a_message(
            agent_id,
            description,
            parameters,
            user_id,
            stream=True,
            output_format=output_format,
            requires_human_approval=requires_human_approval,
        )

    async def get_a2a_task_status(self, agent_id: str, task_id: str) -> dict[str, Any]:
        """Get task status via A2A protocol."""
        base_url = self.client.base_url
        headers = self.client._get_headers()
        url = f"{base_url}/v1/agents/{agent_id}/a2a/rpc"

        request_data = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/get",
            "params": {"id": task_id},
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=request_data, headers=headers)
            if response.status_code == 200:
                response_data = response.json()
                if "result" in response_data:
                    return response_data["result"]
                elif "error" in response_data:
                    error = response_data["error"]
                    raise Exception(f"A2A Error {error.get('code')}: {error.get('message')}")
            else:
                error_text = response.text
                raise Exception(f"HTTP {response.status_code}: {error_text}")

    async def _process_a2a_stream(self, response, output_format: str):
        """Process A2A streaming response with normalized event formatting."""
        if output_format == "json":
            events_data = []
            current_event_name: str | None = None
            async for line in response.aiter_lines():
                line_str = line.strip()
                if not line_str:
                    continue
                if line_str.startswith("event: "):
                    current_event_name = line_str[len("event: ") :].strip()
                    continue
                if line_str.startswith("data: "):
                    data_str = line_str[6:]  # Remove 'data: ' prefix
                    if data_str == "[DONE]":
                        break
                    try:
                        event_data = json.loads(data_str)
                        # Attach SSE event name if not present in payload
                        if current_event_name and "event" not in event_data:
                            event_data["event"] = current_event_name
                        events_data.append(event_data)
                    except json.JSONDecodeError:
                        continue
            click.echo(json.dumps(events_data, indent=2))
        else:
            # Stream in text format similar to internal streaming
            agent_name = None
            current_response = ""
            is_streaming_response = False
            current_event_name: str | None = None

            async for line in response.aiter_lines():
                line_str = line.strip()
                if not line_str:
                    continue
                if line_str.startswith("event: "):
                    current_event_name = line_str[len("event: ") :].strip()
                    continue
                if line_str.startswith("data: "):
                    data_str = line_str[6:]  # Remove 'data: ' prefix
                    if data_str == "[DONE]":
                        break

                    try:
                        event_data = json.loads(data_str)
                        # Inject SSE event name into payload for normalization/matching
                        if current_event_name and "event" not in event_data:
                            event_data["event"] = current_event_name

                        # Normalize A2A event to internal format for consistent rendering
                        normalized_event = self.normalize_event(event_data, "a2a")

                        # Persist and update streaming state across events
                        (
                            agent_name,
                            is_streaming_response,
                            current_response,
                        ) = await self._display_event(
                            normalized_event, agent_name, is_streaming_response, current_response
                        )

                    except json.JSONDecodeError:
                        continue

    async def _display_event(
        self, event_data: dict, agent_name: str, is_streaming_response: bool, current_response: str
    ):
        """Display event in text format using internal streaming logic, returning updated state."""
        event_type = event_data.get("event_type", "unknown")
        data_payload = event_data.get("data", {})

        # Clean event type (remove workflow. prefix)
        clean_event_type = event_type.replace("workflow.", "")

        # Capture agent name if present on connection
        if event_type == "connected":
            agent_name = self._extract_agent_name(data_payload, agent_name)
            return agent_name, is_streaming_response, current_response

        if event_type == "task_created":
            # Silent task creation
            return agent_name, is_streaming_response, current_response

        # Broaden start/chunk/completed event type matching to cover common A2A schemas
        start_events = {
            "LLMCallStarted",
            "LLMRequestStarted",
            "message.started",
            "message.start",
            "MessageStart",
            "ResponseStarted",
            "response.started",
            "llm_call_started",
            "task_started",
        }
        chunk_events = {
            "LLMCallChunk",
            "LLMResponseChunk",
            "message.delta",
            "delta",
            "chunk",
            "MessageDelta",
            "response.delta",
            "content.delta",
            "llm_call_chunk",
        }
        done_events = {
            "LLMCallCompleted",
            "LLMResponseCompleted",
            "message.completed",
            "message.complete",
            "MessageCompleted",
            "response.completed",
            "response.complete",
            "message.end",
            "llm_call_completed",
        }

        if clean_event_type in start_events:
            if not is_streaming_response:
                agent_name = self._extract_agent_name(data_payload, agent_name or "Agent")
                click.echo(f"🤖 {agent_name or 'Agent'}: ", nl=False)
                is_streaming_response = True
            return agent_name, is_streaming_response, current_response
        elif clean_event_type in chunk_events:
            # If we never saw a start event, start the stream now to avoid missing content
            if not is_streaming_response:
                agent_name = self._extract_agent_name(data_payload, agent_name or "Agent")
                click.echo(f"🤖 {agent_name or 'Agent'}: ", nl=False)
                is_streaming_response = True
            if is_streaming_response:
                chunk = self.extract_chunk_content(event_data)
                if chunk:
                    current_response += chunk
                    click.echo(chunk, nl=False)
            return agent_name, is_streaming_response, current_response
        elif clean_event_type in done_events:
            # Print any final content if we didn't receive chunks
            final_text = self.extract_chunk_content(event_data)
            if not final_text and isinstance(data_payload, dict):
                # Common final content fields on completion events
                result_field = (
                    data_payload.get("result")
                    if isinstance(data_payload.get("result"), dict)
                    else None
                )
                final_text = (
                    data_payload.get("response_text")
                    or (result_field.get("content") if result_field else "")
                    or data_payload.get("content")
                    or data_payload.get("text")
                )
            if final_text:
                if not is_streaming_response:
                    agent_name = self._extract_agent_name(data_payload, agent_name or "Agent")
                    click.echo(f"🤖 {agent_name or 'Agent'}: ", nl=False)
                    is_streaming_response = True
                current_response += final_text
                click.echo(final_text, nl=False)
            if is_streaming_response:
                click.echo()  # New line after streaming or final content
                is_streaming_response = False
            return agent_name, is_streaming_response, current_response
        elif clean_event_type == "ToolCallStarted":
            tool_name = data_payload.get("tool_name", "unknown tool")
            click.echo(f"🔧 Calling {tool_name}...")
            return agent_name, is_streaming_response, current_response
        elif clean_event_type == "ToolCallCompleted":
            tool_name = data_payload.get("tool_name", "tool")
            click.echo(f"✅ {tool_name} completed")
            return agent_name, is_streaming_response, current_response
        elif event_type in ["task_completed", "WorkflowCompleted"]:
            click.echo("\n✅ Task completed")
            return agent_name, is_streaming_response, current_response
        elif event_type in ["task_failed", "WorkflowFailed"]:
            error = data_payload.get("error", "Unknown error")
            click.echo(f"\n❌ Task failed: {error}")
            return agent_name, is_streaming_response, current_response

        # Default: no change
        return agent_name, is_streaming_response, current_response
