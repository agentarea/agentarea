"""Protocol routing utilities for CLI commands."""

import json
import uuid
from typing import TYPE_CHECKING, Any, Dict

import aiohttp
import httpx
import click

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
    def extract_chunk_content(event_data: dict) -> str:
        """Extract chunk content from event data, checking both locations."""
        # Check original_data.chunk first (filtered internal streams)
        original_data = event_data.get("original_data", {})
        chunk = original_data.get("chunk", "")
        
        if not chunk:
            # Check data.chunk (direct internal streams)
            data_payload = event_data.get("data", {})
            chunk = data_payload.get("chunk", "")
            
        return chunk

    async def send_a2a_message(
        self,
        agent_id: str,
        message: str,
        parameters: dict = None,
        user_id: str = "cli_user",
        stream: bool = False,
        output_format: str = "text"
    ) -> Any:
        """Send message via A2A protocol."""
        base_url = self.client.base_url
        headers = self.client._get_headers()
        url = f"{base_url}/v1/agents/{agent_id}/a2a/rpc"
        
        # Use streaming method if requested
        method = "message/stream" if stream else "message/send"
        
        # Include parameters in message if provided
        message_text = message
        if parameters:
            message_text += f"\nParameters: {json.dumps(parameters)}"
        
        # Prepare JSON-RPC request
        request_data = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": {
                "message": {
                    "role": "user",
                    "parts": [{"text": message_text}]
                }
            }
        }
        
        if stream:
            # Return streaming response
            async with httpx.AsyncClient(timeout=300) as client:
                async with client.stream(
                    "POST",
                    url,
                    json=request_data,
                    headers=headers
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
        parameters: dict = None,
        user_id: str = "cli_user",
        timeout: int = 300,
        output_format: str = "text"
    ):
        """Stream task creation via A2A protocol using message/stream."""
        # Use message/stream for creating and streaming task
        await self.send_a2a_message(
            agent_id, 
            description, 
            parameters, 
            user_id, 
            stream=True, 
            output_format=output_format
        )

    async def get_a2a_task_status(
        self,
        agent_id: str,
        task_id: str
    ) -> Dict[str, Any]:
        """Get task status via A2A protocol."""
        base_url = self.client.base_url
        headers = self.client._get_headers()
        url = f"{base_url}/v1/agents/{agent_id}/a2a/rpc"
        
        request_data = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/get",
            "params": {"id": task_id}
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
            async for line in response.aiter_lines():
                line_str = line.strip()
                if line_str.startswith('data: '):
                    data_str = line_str[6:]  # Remove 'data: ' prefix
                    if data_str == '[DONE]':
                        break
                    try:
                        event_data = json.loads(data_str)
                        events_data.append(event_data)
                    except json.JSONDecodeError:
                        continue
            click.echo(json.dumps(events_data, indent=2))
        else:
            # Stream in text format similar to internal streaming
            agent_name = None
            current_response = ""
            is_streaming_response = False
            
            async for line in response.aiter_lines():
                line_str = line.strip()
                if line_str.startswith('data: '):
                    data_str = line_str[6:]  # Remove 'data: ' prefix
                    if data_str == '[DONE]':
                        break
                    
                    try:
                        event_data = json.loads(data_str)
                        # Normalize A2A event to internal format for consistent rendering
                        normalized_event = self.normalize_event(event_data, "a2a")
                        
                        # Process the event similarly to internal streaming
                        await self._display_event(normalized_event, agent_name, is_streaming_response, current_response)
                        
                    except json.JSONDecodeError:
                        continue

    async def _display_event(self, event_data: dict, agent_name: str, is_streaming_response: bool, current_response: str):
        """Display event in text format using internal streaming logic."""
        event_type = event_data.get("event_type", "unknown")
        data_payload = event_data.get("data", {})
        
        # Clean event type (remove workflow. prefix)
        clean_event_type = event_type.replace("workflow.", "")
        
        if event_type == "task_created":
            # Silent task creation
            pass
        elif clean_event_type in ["LLMCallStarted", "LLMRequestStarted"]:
            # Start agent response
            agent_name = data_payload.get('agent_name', 'Agent')
            click.echo(f"🤖 {agent_name}: ", nl=False)
            is_streaming_response = True
        elif clean_event_type in ["LLMCallChunk", "LLMResponseChunk"]:
            if is_streaming_response:
                chunk = self.extract_chunk_content(event_data)
                if chunk:
                    current_response += chunk
                    click.echo(chunk, nl=False)
        elif clean_event_type in ["LLMCallCompleted", "LLMResponseCompleted"]:
            if is_streaming_response:
                click.echo()  # New line after streaming
                is_streaming_response = False
        elif clean_event_type == "ToolCallStarted":
            tool_name = data_payload.get("tool_name", "unknown tool")
            click.echo(f"🔧 Calling {tool_name}...")
        elif clean_event_type == "ToolCallCompleted":
            tool_name = data_payload.get("tool_name", "tool")
            click.echo(f"✅ {tool_name} completed")
        elif event_type in ["task_completed", "WorkflowCompleted"]:
            click.echo("\n✅ Task completed")
        elif event_type in ["task_failed", "WorkflowFailed"]:
            error = data_payload.get("error", "Unknown error")
            click.echo(f"\n❌ Task failed: {error}")