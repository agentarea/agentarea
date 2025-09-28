"""Task management commands for AgentArea CLI."""

import json
from datetime import datetime
from typing import TYPE_CHECKING

import click
import httpx

from agentarea_cli.client import run_async
from agentarea_cli.exceptions import APIError as AgentAreaAPIError
from agentarea_cli.exceptions import AuthenticationError
from agentarea_cli.utils import format_table, safe_get_field
from agentarea_cli.protocol_routing import ProtocolRouter

if TYPE_CHECKING:
    from agentarea_cli.client import AgentAreaClient
    from agentarea_cli.config import AuthConfig


@click.group()
def task():
    """Task management and execution commands."""
    pass


@task.command()
@click.option("--agent-id", required=True, help="Agent ID to execute the task")
@click.option("--description", required=True, help="Task description")
@click.option("--parameters", help="JSON string of task parameters")
@click.option("--user-id", default="cli_user", help="User ID")
@click.option("--stream/--no-stream", default=True, help="Stream task execution events")
@click.option("--timeout", default=300, help="Timeout in seconds for task execution")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.option("--protocol", type=click.Choice(["internal", "a2a"]), default="internal", help="Protocol to use for communication")
@click.option("--requires-human-approval/--no-requires-human-approval", default=False, help="Require human approval before task runs")
@click.pass_context
def create(ctx, agent_id: str, description: str, parameters: str | None, user_id: str,
          stream: bool, timeout: int, output_format: str, protocol: str, requires_human_approval: bool):
    """Create and execute a task for an agent with real-time event streaming."""
    client: "AgentAreaClient" = ctx.obj["client"]

    # Try parsing parameters JSON
    params_dict = {}
    if parameters:
        try:
            params_dict = json.loads(parameters)
        except json.JSONDecodeError as e:
            click.echo(f"Invalid JSON for parameters: {e}")
            raise click.Abort()

    if protocol == "a2a":
        router = ProtocolRouter(client)
        if stream:
            # Stream A2A task creation, which will output normalized events
            return run_async(router.stream_task_create_a2a(agent_id, description, params_dict, user_id, timeout, output_format, requires_human_approval))
        else:
            # Non-streaming A2A send: use message/send to get final response
            return run_async(router.send_a2a_message(agent_id, description, params_dict, user_id, stream=False, output_format=output_format, requires_human_approval=requires_human_approval))

    # Internal protocol existing behavior
    if stream:
        # Build task_data payload for internal streaming endpoint
        task_data = {
            "description": description,
            "parameters": params_dict or {},
            "user_id": user_id,
            "requires_human_approval": requires_human_approval,
        }
        return run_async(_stream_task_creation(client, agent_id, task_data, timeout, output_format))

    # Non-streaming internal sync endpoint
    async def _create_task_sync():
        try:
            payload = {
                "description": description,
                "parameters": params_dict or {},
                "user_id": user_id,
                "mode": "sync",
                "timeout": timeout,
                "requires_human_approval": requires_human_approval,
            }
            url = f"{client.base_url}/v1/agents/{agent_id}/tasks/sync"
            headers = client._get_headers()
            async with httpx.AsyncClient(timeout=timeout + 5) as http_client:
                resp = await http_client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                data = resp.json()
                if output_format == "json":
                    click.echo(json.dumps(data, indent=2))
                else:
                    result = data.get("result") or {}
                    output_text = result.get("output", "") or result.get("content", "")
                    click.echo(output_text)
        except httpx.HTTPStatusError as e:
            click.echo(f"HTTP error: {e.response.status_code} - {e.response.text}")
            raise click.Abort()
        except (AuthenticationError, AgentAreaAPIError) as e:
            click.echo(f"Error: {e}")
            raise click.Abort()

    return run_async(_create_task_sync())


async def _stream_task_creation(
    client: "AgentAreaClient",
    agent_id: str,
    task_data: dict,
    timeout: int,
    output_format: str
):
    """Stream task creation and execution events with chat-like interface."""
    base_url = client.base_url
    headers = client._get_headers()
    headers["Accept"] = "text/event-stream"

    async with httpx.AsyncClient(timeout=timeout) as http_client:
        async with http_client.stream(
            "POST",
            f"{base_url}/v1/agents/{agent_id}/tasks/",
            json=task_data,
            headers=headers
        ) as response:

            if response.status_code != 200:
                error_text = await response.aread()
                raise AgentAreaAPIError(f"HTTP {response.status_code}: {error_text.decode()}")

            if output_format == "json":
                events_data = []
                async for line in response.aiter_lines():
                    if line.strip().startswith('data:'):
                        try:
                            data = line.strip()[5:].strip()
                            event_data = json.loads(data)
                            events_data.append(event_data)
                        except json.JSONDecodeError:
                            continue
                click.echo(json.dumps(events_data, indent=2))
                return

            # Natural conversation interface - no announcement needed

            # State tracking for chat interface
            task_id = None
            execution_id = None
            agent_name = None
            current_response = ""
            is_streaming_response = False
            workflow_completed = False

            async for line in response.aiter_lines():
                line = line.strip()

                if not line.startswith('data:'):
                    continue

                try:
                    data = line[5:].strip()
                    event_data = json.loads(data)

                    # Extract event information
                    event_type = event_data.get("event_type", "unknown")
                    timestamp = event_data.get("timestamp", datetime.now().isoformat())
                    data_payload = event_data.get("data", {})

                    # Clean event type (remove workflow. prefix)
                    clean_event_type = event_type.replace("workflow.", "")

                    # Format timestamp for display
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        time_str = dt.strftime("%H:%M:%S")
                    except:
                        time_str = timestamp[:8] if len(timestamp) > 8 else timestamp

                    # Handle different event types with natural conversation flow
                    if event_type == "connected":
                        agent_name = data_payload.get('agent_name', 'Agent')
                        # Silent connection - let the conversation flow naturally

                    elif event_type == "task_created":
                        task_id = data_payload.get("task_id")
                        execution_id = data_payload.get("execution_id")
                        # Just store the IDs, no output needed

                    elif clean_event_type == "WorkflowStarted":
                        # Silent - no need to announce workflow start
                        pass

                    elif clean_event_type == "IterationStarted":
                        # Silent - let the agent speak naturally
                        pass

                    elif clean_event_type in ["LLMCallStarted", "LLMRequestStarted"]:
                        # Start agent response naturally (guard to avoid duplicate prefixes)
                        if not is_streaming_response:
                            click.echo(f"🤖 {agent_name or 'Agent'}: ", nl=False)
                            is_streaming_response = True
                            current_response = ""

                    elif clean_event_type in ["LLMCallChunk", "LLMResponseChunk"]:
                        if is_streaming_response:
                            # Extract chunk robustly from multiple possible fields
                            original_data = event_data.get("original_data", {}) or {}
                            chunk = (
                                original_data.get("chunk")
                                or (original_data.get("delta", {}) or {}).get("text")
                                or data_payload.get("chunk")
                                or (data_payload.get("delta", {}) or {}).get("text")
                                or original_data.get("content")
                                or data_payload.get("content")
                                or original_data.get("text")
                                or data_payload.get("text")
                            )
                            if isinstance(chunk, (dict, list)):
                                chunk = str(chunk)
                            if chunk:
                                current_response += chunk
                                # Print chunk without newline to create streaming effect
                                click.echo(chunk, nl=False)

                    elif clean_event_type in ["LLMCallCompleted", "LLMResponseCompleted"]:
                        if is_streaming_response:
                            click.echo()  # New line after streaming
                            is_streaming_response = False
                            # No need to show token usage in natural conversation
                        else:
                            # If we weren't streaming, show the complete content
                            original_data = data_payload.get("original_data", data_payload)
                            content = original_data.get("content", data_payload.get("content"))
                            if content and content.strip():
                                click.echo(f"🤖 {agent_name or 'Agent'}: {content}")

                    elif clean_event_type == "ToolCallStarted":
                        tool_name = data_payload.get("tool_name", "unknown tool")
                        # Extract tool arguments if available
                        original_data = data_payload.get("original_data", {})
                        arguments = original_data.get("arguments", data_payload.get("arguments"))
                        if arguments:
                            if isinstance(arguments, dict):
                                # Show a preview of the arguments
                                args_preview = str(arguments)[:100]
                                if len(str(arguments)) > 100:
                                    args_preview += "..."
                                click.echo(f"🔧 Calling {tool_name} with: {args_preview}")
                            else:
                                click.echo(f"🔧 Calling {tool_name}...")
                        else:
                            click.echo(f"🔧 Calling {tool_name}...")

                    elif clean_event_type == "ToolCallCompleted":
                        tool_name = data_payload.get("tool_name", "tool")
                        # Extract tool result if available
                        original_data = event_data.get("original_data", {})
                        result = original_data.get("result", data_payload.get("result"))
                        success = original_data.get("success", data_payload.get("success", True))

                        if success and result:
                            # If this looks like content the user should see, display it naturally
                            result_str = str(result).strip()
                            if result_str:  # Display any non-empty result
                                # Only elevate task_complete as primary output; no content-based heuristics
                                if tool_name == "task_complete":
                                    # Don't add Agent prefix here - it's already handled by streaming
                                    click.echo(f"\n{result_str}")
                                else:
                                    # Show tool result briefly
                                    result_preview = result_str[:100] + "..." if len(result_str) > 100 else result_str
                                    click.echo(f"🔧 {tool_name}: {result_preview}")
                        # Don't show anything for empty or failed tool calls

                    elif clean_event_type == "IterationCompleted":
                        # Silent - no need to announce iteration completion
                        pass

                    elif clean_event_type == "WorkflowCompleted":
                        workflow_completed = True
                        # Extract the final result from the workflow
                        result = (event_data.get("result") or
                                event_data.get("final_response") or
                                data_payload.get("result") or
                                data_payload.get("final_response"))

                        if result and result.strip():
                            # If we haven't streamed any content yet, show the result
                            if not current_response.strip():
                                click.echo(f"🤖 {agent_name or 'Agent'}: {result}")
                            # If the result is different from what we streamed, show it
                            elif result != current_response.strip():
                                click.echo(f"\n📄 Final result: {result}")
                        break

                    elif clean_event_type == "WorkflowFailed":
                        error = data_payload.get("error", "Unknown error")
                        error_type = data_payload.get("error_type")
                        if error_type:
                            click.echo(f"\n❌ Task failed ({error_type}): {error}")
                        else:
                            click.echo(f"\n❌ Task failed: {error}")
                        break

                    elif event_type == "task_failed":
                        error = data_payload.get("error", "Unknown error")
                        click.echo(f"\n❌ Task failed: {error}")
                        break

                    elif event_type == "error":
                        error = data_payload.get("error", "Unknown error")
                        click.echo(f"\n❌ Error: {error}")
                        break

                    elif clean_event_type == "LLMCallFailed":
                        # Extract enriched error information
                        original_data = data_payload.get("original_data", data_payload)
                        error = original_data.get("error", data_payload.get("error", "LLM call failed"))

                        # Show user-friendly error messages
                        if original_data.get("is_auth_error") or data_payload.get("is_auth_error"):
                            provider = original_data.get("provider_type", data_payload.get("provider_type", ""))
                            click.echo(f"\n❌ Authentication failed{f' for {provider}' if provider else ''}. Please check your API key.")
                        elif original_data.get("is_rate_limit_error") or data_payload.get("is_rate_limit_error"):
                            retry_after = original_data.get("retry_after", data_payload.get("retry_after"))
                            click.echo(f"\n⏳ Rate limit exceeded{f'. Retry after {retry_after} seconds' if retry_after else ''}.")
                        elif original_data.get("is_quota_error") or data_payload.get("is_quota_error"):
                            click.echo("\n💳 Quota exceeded. Please check your billing settings.")
                        else:
                            click.echo(f"\n❌ LLM error: {error}")

                    elif event_type == "heartbeat":
                        # Silent heartbeat - just keep connection alive
                        pass

                    # Handle any other events that might contain useful information
                    else:
                        # Look for meaningful content in the event
                        message = (data_payload.get("message") or
                                 data_payload.get("content") or
                                 data_payload.get("description"))
                        if message and message.strip() and len(message) > 5:  # Ignore very short messages
                            click.echo(f"📡 {clean_event_type}: {message}")

                except json.JSONDecodeError:
                    # Silently skip malformed JSON
                    continue
                except Exception:
                    # Silently skip processing errors to avoid cluttering output
                    continue

            # End naturally - no verbose summary needed
            if not workflow_completed:
                click.echo("\n⚠️  Conversation interrupted")
            # Task ID available for reference if needed, but don't clutter the output


@task.command()
@click.option("--agent-id", help="Filter by agent ID")
@click.option("--status", help="Filter by status (running, completed, failed, etc.)")
@click.option("--limit", default=10, help="Maximum number of tasks to show")
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
@click.pass_context
def list(ctx, agent_id: str | None, status: str | None, limit: int, output_format: str):
    """List tasks with optional filtering."""

    async def _list_tasks():
        client: AgentAreaClient = ctx.obj["client"]
        auth_config: AuthConfig = ctx.obj["auth_config"]

        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()

        try:
            # Build query parameters
            params = {"limit": limit}
            if status:
                params["status"] = status

            # Choose endpoint based on agent filter
            if agent_id:
                endpoint = f"/v1/agents/{agent_id}/tasks/"
            else:
                endpoint = "/v1/tasks/"

            data = await client.get(endpoint, params=params)

            if not data:
                click.echo("📭 No tasks found")
                return

            # Ensure data is a list
            if not hasattr(data, '__iter__') or isinstance(data, str):
                click.echo("📭 No tasks found")
                return

            if output_format == "json":
                click.echo(json.dumps(data, indent=2))
                return

            # Table format
            click.echo(f"📋 Tasks ({len(data)} found):")
            click.echo()

            headers = ["ID", "Agent", "Description", "Status", "Created"]
            rows = []

            for task in data:
                task_id = safe_get_field(task, "id")
                agent_name = safe_get_field(task, "agent_name", "N/A")
                description = safe_get_field(task, "description")
                task_status = safe_get_field(task, "status")
                created_at = safe_get_field(task, "created_at")

                # Format timestamp
                try:
                    dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                    time_str = dt.strftime("%m-%d %H:%M")
                except:
                    time_str = created_at[:16] if len(created_at) > 16 else created_at

                # Status emoji
                status_emoji = {
                    "completed": "✅",
                    "running": "🏃",
                    "pending": "⏳",
                    "failed": "❌",
                    "cancelled": "🚫"
                }.get(task_status.lower(), "❓")

                # Truncate description
                desc_short = description[:40] + "..." if len(description) > 40 else description

                rows.append([
                    task_id[:8] + "...",  # Truncate ID
                    agent_name[:15] + "..." if len(agent_name) > 15 else agent_name,
                    desc_short,
                    f"{status_emoji} {task_status}",
                    time_str
                ])

            click.echo(format_table(headers, rows))

        except AuthenticationError:
            click.echo("❌ Authentication failed. Please login again with 'agentarea auth login'")
            raise click.Abort()
        except AgentAreaAPIError as e:
            click.echo(f"❌ Error listing tasks: {e}")
            raise click.Abort()

    run_async(_list_tasks())


@task.command()
@click.argument("task_id")
@click.option("--agent-id", help="Agent ID (required if not using global task ID)")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.pass_context
def status(ctx, task_id: str, agent_id: str | None, output_format: str):
    """Get detailed status of a specific task."""

    async def _get_status():
        client: AgentAreaClient = ctx.obj["client"]
        auth_config: AuthConfig = ctx.obj["auth_config"]

        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()

        try:
            if agent_id:
                endpoint = f"/v1/agents/{agent_id}/tasks/{task_id}/status"
            else:
                # Try to get task from global endpoint first
                endpoint = f"/v1/tasks/{task_id}/status"

            data = await client.get(endpoint)

            if output_format == "json":
                click.echo(json.dumps(data, indent=2))
                return

            # Text format
            click.echo(f"📋 Task Status: {task_id}")
            click.echo("=" * 50)

            status = safe_get_field(data, "status")
            execution_id = safe_get_field(data, "execution_id")
            start_time = safe_get_field(data, "start_time")
            end_time = safe_get_field(data, "end_time")
            execution_time = safe_get_field(data, "execution_time")
            error = safe_get_field(data, "error")
            result = safe_get_field(data, "result")

            # Status with emoji
            status_emoji = {
                "completed": "✅",
                "running": "🏃",
                "pending": "⏳",
                "failed": "❌",
                "cancelled": "🚫"
            }.get(status.lower(), "❓")

            click.echo(f"Status: {status_emoji} {status}")
            if execution_id != "Unknown":
                click.echo(f"Execution ID: {execution_id}")
            if start_time != "Unknown":
                click.echo(f"Started: {start_time}")
            if end_time != "Unknown":
                click.echo(f"Ended: {end_time}")
            if execution_time != "Unknown":
                click.echo(f"Duration: {execution_time}")

            if error != "Unknown":
                click.echo(f"❌ Error: {error}")

            if result != "Unknown" and result:
                click.echo("📄 Result:")
                if isinstance(result, dict):
                    click.echo(json.dumps(result, indent=2))
                else:
                    click.echo(str(result))

        except AuthenticationError:
            click.echo("❌ Authentication failed. Please login again with 'agentarea auth login'")
            raise click.Abort()
        except AgentAreaAPIError as e:
            click.echo(f"❌ Error getting task status: {e}")
            raise click.Abort()

    run_async(_get_status())


@task.command()
@click.argument("task_id")
@click.option("--agent-id", help="Agent ID (required if not using global task ID)")
@click.option("--follow", "-f", is_flag=True, help="Follow/stream live events")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.option("--protocol", type=click.Choice(["internal", "a2a"]), default="internal", help="Protocol to use for communication")
@click.pass_context
def events(ctx, task_id: str, agent_id: str | None, follow: bool, output_format: str, protocol: str):
    """View task execution events."""

    async def _get_events():
        client: AgentAreaClient = ctx.obj["client"]
        auth_config: AuthConfig = ctx.obj["auth_config"]

        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()

        try:
            if follow:
                # Stream live events
                if not agent_id:
                    click.echo("❌ Agent ID is required for streaming events")
                    raise click.Abort()

                if output_format == "text":
                    click.echo(f"🎧 Streaming live events for task {task_id}...")
                    click.echo("Press Ctrl+C to stop")
                    click.echo("-" * 60)

                await _stream_task_events(client, agent_id, task_id, output_format, protocol)

            else:
                # Get historical events
                if protocol == "a2a":
                    if not agent_id:
                        click.echo("❌ Agent ID is required for A2A protocol")
                        raise click.Abort()
                    router = ProtocolRouter(client)
                    status = await router.get_a2a_task_status(agent_id, task_id)
                    # A2A tasks/get returns status structure; display some info
                    if output_format == "json":
                        click.echo(json.dumps(status, indent=2))
                        return
                    state = safe_get_field(status, "status.state", "unknown")
                    click.echo(f"Task {task_id} state: {state}")
                    # If events history is not available over A2A, inform user
                    click.echo("ℹ️ Detailed event history is not available via A2A. Use internal protocol for full events.")
                    return
                else:
                    endpoint = f"/v1/agents/{agent_id}/tasks/{task_id}/events" if agent_id else f"/v1/tasks/{task_id}/events"
                    data = await client.get(endpoint)

                    events = data.get("events", []) if isinstance(data, dict) else data

                    if output_format == "json":
                        click.echo(json.dumps(events, indent=2))
                        return

                    if events:
                        click.echo(f"📋 Task Events: {task_id}")
                        click.echo("=" * 50)

                        for event in events:
                            event_type = safe_get_field(event, "event_type")
                            timestamp = safe_get_field(event, "timestamp")
                            message = safe_get_field(event, "message")

                            # Format timestamp
                            try:
                                dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                                time_str = dt.strftime("%Y-%m-%d %H:%M:%S")
                            except:
                                time_str = timestamp

                            click.echo(f"[{time_str}] {event_type}: {message}")
                    else:
                        click.echo("📭 No events found for this task")

        except KeyboardInterrupt:
            if output_format == "text":
                click.echo("\n🛑 Stopped")
        except AuthenticationError:
            click.echo("❌ Authentication failed. Please login again with 'agentarea auth login'")
            raise click.Abort()
        except AgentAreaAPIError as e:
            click.echo(f"❌ Error getting events: {e}")
            raise click.Abort()

    run_async(_get_events())


async def _stream_task_events(
    client: "AgentAreaClient",
    agent_id: str,
    task_id: str,
    output_format: str,
    protocol: str = "internal"
):
    """Stream live task events."""
    if protocol == "a2a":
        # Route to A2A streaming - note: A2A doesn't have dedicated events streaming
        # For now, we'll show a helpful message
        click.echo("ℹ️ A2A protocol doesn't support dedicated event streaming for existing tasks.")
        click.echo("   Use 'agentarea a2a get-task' to check task status instead.")
        return
    
    # Internal streaming implementation
    base_url = client.base_url
    headers = client._get_headers()
    headers["Accept"] = "text/event-stream"

    events_data = []

    async with httpx.AsyncClient(timeout=300) as http_client:
        async with http_client.stream(
            "GET",
            f"{base_url}/v1/agents/{agent_id}/tasks/{task_id}/events/stream",
            headers=headers
        ) as response:

            if response.status_code != 200:
                error_text = await response.aread()
                raise AgentAreaAPIError(f"HTTP {response.status_code}: {error_text.decode()}")

            async for line in response.aiter_lines():
                line = line.strip()

                if line.startswith('data:'):
                    try:
                        data = line[5:].strip()
                        event_data = json.loads(data)

                        if output_format == "json":
                            events_data.append(event_data)
                            # Print each event as it comes in JSON mode
                            click.echo(json.dumps(event_data, indent=2))
                            continue

                        event_type = event_data.get("event_type", "unknown")
                        timestamp = event_data.get("timestamp", "")
                        data_payload = event_data.get("data", {})

                        # Format timestamp
                        try:
                            dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                            time_str = dt.strftime("%H:%M:%S")
                        except:
                            time_str = timestamp[:8] if len(timestamp) > 8 else timestamp

                        message = data_payload.get("message", f"Event: {event_type}")
                        click.echo(f"[{time_str}] {event_type}: {message}")

                    except json.JSONDecodeError:
                        continue
                    except KeyboardInterrupt:
                        if output_format == "text":
                            click.echo("\n🛑 Stopped streaming")
                        break


@task.command()
@click.option("--agent-id", required=True, help="Agent ID to chat with")
@click.option("--message", "-m", help="Single message to send (if not provided, enters interactive mode)")
@click.option("--timeout", default=300, help="Timeout in seconds for each message")
@click.option("--protocol", type=click.Choice(["internal", "a2a"]), default="internal", help="Protocol to use for communication")
@click.pass_context
def chat(ctx, agent_id: str, message: str | None, timeout: int, protocol: str):
    """Chat with an agent in a conversational interface."""

    async def _chat():
        client: AgentAreaClient = ctx.obj["client"]
        auth_config: AuthConfig = ctx.obj["auth_config"]

        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()

        if message:
            # Single message mode
            await _send_single_message(client, agent_id, message, timeout, protocol)
        else:
            # Interactive chat mode
            await _interactive_chat(client, agent_id, timeout, protocol)

    run_async(_chat())


async def _send_single_message(client: "AgentAreaClient", agent_id: str, message: str, timeout: int, protocol: str):
    """Send a single message and display the response."""
    click.echo(f"💬 You: {message}")
    click.echo()

    if protocol == "a2a":
        router = ProtocolRouter(client)
        # Use A2A streaming to send the message
        await router.send_a2a_message(agent_id=agent_id, message=message, parameters={"task_type": "chat", "created_via": "cli_task_chat"}, stream=True, output_format="text")
        return

    # Internal default: create a task and stream its events
    task_data = {
        "description": message,
        "parameters": {
            "task_type": "chat",
            "session_id": f"cli-chat-{int(datetime.now().timestamp())}",
            "created_via": "cli_chat"
        },
        "user_id": "cli_user",
        "enable_agent_communication": True,
    }

    await _stream_task_creation(client, agent_id, task_data, timeout, "text")


async def _interactive_chat(client: "AgentAreaClient", agent_id: str, timeout: int, protocol: str):
    """Start an interactive chat session."""
    click.echo("💬 Interactive Chat Mode")
    click.echo("Commands: 'exit' or 'quit' to end, 'clear' for new session")
    click.echo("=" * 60)

    session_id = f"cli-interactive-{int(datetime.now().timestamp())}"
    message_count = 0

    while True:
        try:
            # Get user input
            user_input = click.prompt("You", type=str).strip()

            if user_input.lower() in ['exit', 'quit']:
                click.echo("👋 Goodbye!")
                break

            if user_input.lower() == 'clear':
                session_id = f"cli-interactive-{int(datetime.now().timestamp())}"
                message_count = 0
                click.echo("🔄 Started new conversation")
                continue

            if not user_input:
                continue

            message_count += 1
            click.echo()  # Add space before agent response

            if protocol == "a2a":
                router = ProtocolRouter(client)
                await router.send_a2a_message(
                    agent_id=agent_id,
                    message=user_input,
                    parameters={
                        "task_type": "chat",
                        "session_id": session_id,
                        "created_via": "cli_interactive",
                        "message_number": message_count
                    },
                    stream=True,
                    output_format="text"
                )
                click.echo()  # Add space after agent response
                continue

            # Internal default path: create a task per message and stream
            task_data = {
                "description": user_input,
                "parameters": {
                    "task_type": "chat",
                    "session_id": session_id,
                    "created_via": "cli_interactive",
                    "message_number": message_count
                },
                "user_id": "cli_user",
                "enable_agent_communication": True,
            }

            await _stream_task_creation(client, agent_id, task_data, timeout, "text")
            click.echo()  # Add space after agent response

        except KeyboardInterrupt:
            click.echo("\n👋 Goodbye!")
            break
        except EOFError:
            click.echo("\n👋 Goodbye!")
            break
        except Exception as e:
            click.echo(f"❌ Error: {e}")
            continue


@task.command()
@click.argument("task_id")
@click.option("--agent-id", help="Agent ID (required if not using global task ID)")
@click.pass_context
def cancel(ctx, task_id: str, agent_id: str | None):
    """Cancel a running task."""

    async def _cancel_task():
        client: AgentAreaClient = ctx.obj["client"]
        auth_config: AuthConfig = ctx.obj["auth_config"]

        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()

        try:
            if agent_id:
                endpoint = f"/v1/agents/{agent_id}/tasks/{task_id}"
            else:
                endpoint = f"/v1/tasks/{task_id}"

            result = await client.delete(endpoint)

            status = result.get("status", "unknown")
            if status == "cancelled":
                click.echo(f"✅ Task {task_id} cancelled successfully")
            else:
                click.echo(f"⚠️  Task {task_id} status: {status}")

        except AuthenticationError:
            click.echo("❌ Authentication failed. Please login again with 'agentarea auth login'")
            raise click.Abort()
        except AgentAreaAPIError as e:
            click.echo(f"❌ Error cancelling task: {e}")
            raise click.Abort()

    run_async(_cancel_task())
