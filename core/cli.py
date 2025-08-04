import asyncio
import json
import os
import sys
from typing import Any

import click
import httpx
import uvicorn
from agentarea_common.config import Database, get_db_settings
from sqlalchemy import text
from sqlalchemy.engine import Engine

from alembic import command
from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory


def get_engine():
    """Get database engine with retry logic."""
    db = Database(get_db_settings())
    # Use the synchronous engine for migration operations
    return db.sync_engine


def check_database_connection():
    """Check database connection using SQLAlchemy's built-in retry logic."""
    engine = get_engine()
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        return True
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        raise


def get_current_revision(engine: Engine) -> str | None:
    try:
        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            return context.get_current_revision()
    except Exception as e:
        print(f"Failed to get current revision: {e}")
        return None


def get_head_revision() -> str | None:
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    return script.get_current_head()


def check_migrations_status():
    """Check if all migrations are up to date."""
    engine = get_engine()
    current = get_current_revision(engine)
    head = get_head_revision()

    if current == head:
        print("Migrations are up to date")
        return True
    print(f"Waiting for migrations... (current: {current}, target: {head})")
    raise Exception("Migrations not up to date")


async def make_api_request(
    method: str,
    endpoint: str,
    data: dict[str, Any] | None = None,
    base_url: str = "http://localhost:8000",
) -> dict[str, Any]:
    """Make HTTP request to the API."""
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        url = f"{base_url}{endpoint}"
        try:
            if method.upper() == "GET":
                response = await client.get(url)
            elif method.upper() == "POST":
                response = await client.post(url, json=data or {})
            elif method.upper() == "PUT":
                response = await client.put(url, json=data or {})
            elif method.upper() == "DELETE":
                response = await client.delete(url)
            else:
                raise ValueError(f"Unsupported method: {method}")

            response.raise_for_status()
            return response.json()
        except httpx.ConnectError:
            click.echo(f"❌ Cannot connect to API server at {base_url}")
            click.echo("   Make sure the server is running with: python -m cli serve")
            raise
        except httpx.HTTPStatusError as e:
            click.echo(f"❌ HTTP {e.response.status_code}: {e.response.text}")
            raise
        except Exception as e:
            click.echo(f"❌ Request failed: {e}")
            raise


def safe_get_field(item: Any, field: str, default: str = "Unknown") -> str:
    """Safely get a field from an item, handling various data types."""
    if item is None:
        return default
    if isinstance(item, dict):
        return item.get(field, default)
    if hasattr(item, field):
        return getattr(item, field, default)
    return str(item)


@click.group()
def cli():
    """AgentArea CLI - Manage LLMs, MCPs, Agents, and Tasks."""
    pass


@cli.command()
def migrate():
    """Run database migrations."""
    try:
        check_database_connection()
        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        print("Migrations completed successfully")
    except Exception as e:
        print(f"Migration failed: {e}")
        sys.exit(1)


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host to bind the server to")
@click.option(
    "--port",
    default=lambda: int(os.getenv("PORT", 8000)),
    help="Port to bind the server to",
)
@click.option(
    "--reload/--no-reload",
    default=False,
    help="Enable/disable auto-reload on code changes",
)
@click.option(
    "--log-level",
    default="info",
    type=click.Choice(["critical", "error", "warning", "info", "debug", "trace"]),
    help="Logging level",
)
@click.option("--access-log/--no-access-log", default=True, help="Enable/disable access logs")
@click.option("--workers", default=1, help="Number of worker processes")
def serve(host: str, port: int, reload: bool, log_level: str, access_log: bool, workers: int):
    """Start the main application server."""
    # check_migrations_status()  # Temporarily disabled for testing

    print(
        f"Starting server on {host}:{port} (reload={reload}, log_level={log_level}, workers={workers})"
    )

    # Configure uvicorn
    uvicorn.run(
        app="agentarea_api.main:app",
        host=host,
        port=int(port),  # Ensure port is an integer
        reload=reload,
        workers=workers,
        access_log=access_log,
        log_level=log_level,
    )


# ============================================================================
# LLM Management Commands
# ============================================================================


@cli.group()
def llm():
    """LLM model and instance management commands."""
    pass


@llm.command()
def models():
    """List available LLM models."""

    async def _list_models():
        try:
            data = await make_api_request("GET", "/v1/llm-models")
            if data and hasattr(data, '__iter__') and not isinstance(data, str):
                click.echo("Available LLM Models:")
                for model in data:
                    name = safe_get_field(model, "name")
                    provider = safe_get_field(model, "provider")
                    description = safe_get_field(model, "description")
                    click.echo(f"  • {name} ({provider}) - {description}")
            else:
                click.echo("No LLM models found")
        except Exception as e:
            click.echo(f"Error listing models: {e}")

    asyncio.run(_list_models())


@llm.command()
def instances():
    """List LLM model instances."""

    async def _list_instances():
        try:
            data = await make_api_request("GET", "/v1/llm-models/instances")
            if data and hasattr(data, '__iter__') and not isinstance(data, str):
                click.echo("LLM Model Instances:")
                for instance in data:
                    name = safe_get_field(instance, "name")
                    description = safe_get_field(instance, "description")
                    status = safe_get_field(instance, "status")
                    click.echo(f"  • {name} - {description}")
                    click.echo(f"    Status: {status}")
            else:
                click.echo("No LLM instances found")
        except Exception as e:
            click.echo(f"Error listing instances: {e}")

    asyncio.run(_list_instances())


@llm.command()
@click.option("--name", required=True, help="Model name")
@click.option("--description", required=True, help="Model description")
@click.option("--provider", required=True, help="Provider (e.g., openai, anthropic, ollama)")
@click.option("--model-type", required=True, help="Model type")
@click.option("--endpoint-url", required=True, help="API endpoint URL")
@click.option("--context-window", default="4096", help="Context window size")
@click.option("--is-public/--no-public", default=False, help="Make model public")
def create_model(
    name: str,
    description: str,
    provider: str,
    model_type: str,
    endpoint_url: str,
    context_window: str,
    is_public: bool,
):
    """Create a new LLM model."""

    async def _create_model():
        data = {
            "name": name,
            "description": description,
            "provider": provider,
            "model_type": model_type,
            "endpoint_url": endpoint_url,
            "context_window": context_window,
            "is_public": is_public,
        }

        try:
            result = await make_api_request("POST", "/v1/llm-models", data)
            name_result = safe_get_field(result, "name")
            id_result = safe_get_field(result, "id")
            click.echo(f"✅ Created LLM model: {name_result}")
            click.echo(f"   ID: {id_result}")
        except Exception as e:
            click.echo(f"❌ Error creating model: {e}")

    asyncio.run(_create_model())


@llm.command()
@click.option("--model-id", required=True, help="LLM Model ID")
@click.option("--name", required=True, help="Instance name")
@click.option("--description", required=True, help="Instance description")
@click.option("--api-key", required=True, help="API key for the model")
@click.option("--is-public/--no-public", default=False, help="Make instance public")
def create_instance(model_id: str, name: str, description: str, api_key: str, is_public: bool):
    """Create a new LLM model instance."""

    async def _create_instance():
        data = {
            "model_id": model_id,
            "name": name,
            "description": description,
            "api_key": api_key,
            "is_public": is_public,
        }

        try:
            result = await make_api_request("POST", "/v1/llm-models/instances", data)
            name_result = safe_get_field(result, "name")
            id_result = safe_get_field(result, "id")
            click.echo(f"✅ Created LLM instance: {name_result}")
            click.echo(f"   ID: {id_result}")
        except Exception as e:
            click.echo(f"❌ Error creating instance: {e}")

    asyncio.run(_create_instance())


# ============================================================================
# MCP Management Commands
# ============================================================================


@cli.group()
def mcp():
    """MCP server management commands."""
    pass


@mcp.command()
def servers():
    """List available MCP servers."""

    async def _list_servers():
        try:
            data = await make_api_request("GET", "/v1/mcp-servers")
            if data and hasattr(data, '__iter__') and not isinstance(data, str):
                click.echo("Available MCP Servers:")
                for server in data:
                    name = safe_get_field(server, "name")
                    description = safe_get_field(server, "description")
                    image = safe_get_field(server, "docker_image_url")
                    click.echo(f"  • {name} - {description}")
                    click.echo(f"    Image: {image}")
            else:
                click.echo("No MCP servers found")
        except Exception as e:
            click.echo(f"Error listing servers: {e}")

    asyncio.run(_list_servers())


@mcp.command("instances")
def mcp_instances():
    """List MCP server instances."""

    async def _list_instances():
        try:
            data = await make_api_request("GET", "/v1/mcp-server-instances")
            if data and hasattr(data, '__iter__') and not isinstance(data, str):
                click.echo("MCP Server Instances:")
                for instance in data:
                    name = safe_get_field(instance, "name")
                    endpoint = safe_get_field(instance, "endpoint_url")
                    status = safe_get_field(instance, "status")
                    click.echo(f"  • {name}")
                    click.echo(f"    Endpoint: {endpoint}")
                    click.echo(f"    Status: {status}")
            else:
                click.echo("No MCP instances found")
        except Exception as e:
            click.echo(f"Error listing instances: {e}")

    asyncio.run(_list_instances())


@mcp.command()
@click.option("--name", required=True, help="Server name")
@click.option("--description", required=True, help="Server description")
@click.option("--docker-image", required=True, help="Docker image URL")
@click.option("--version", default="latest", help="Version tag")
@click.option("--tags", help="Comma-separated tags")
@click.option("--is-public/--no-public", default=False, help="Make server public")
def create_server(
    name: str,
    description: str,
    docker_image: str,
    version: str,
    tags: str | None,
    is_public: bool,
):
    """Create a new MCP server."""

    async def _create_server():
        data = {
            "name": name,
            "description": description,
            "docker_image_url": docker_image,
            "version": version,
            "tags": tags.split(",") if tags else [],
            "is_public": is_public,
        }

        try:
            result = await make_api_request("POST", "/v1/mcp-servers", data)
            name_result = safe_get_field(result, "name")
            id_result = safe_get_field(result, "id")
            click.echo(f"✅ Created MCP server: {name_result}")
            click.echo(f"   ID: {id_result}")
        except Exception as e:
            click.echo(f"❌ Error creating server: {e}")

    asyncio.run(_create_server())


@mcp.command()
@click.option("--server-id", required=True, help="MCP Server ID")
@click.option("--name", required=True, help="Instance name")
@click.option("--endpoint-url", required=True, help="MCP endpoint URL")
@click.option("--config", help="JSON configuration string")
def create_mcp_instance(server_id: str, name: str, endpoint_url: str, config: str | None):
    """Create a new MCP server instance."""

    async def _create_instance():
        config_data = {}
        if config:
            try:
                config_data = json.loads(config)
            except json.JSONDecodeError:
                click.echo("❌ Invalid JSON in config parameter")
                return

        data = {
            "server_id": server_id,
            "name": name,
            "endpoint_url": endpoint_url,
            "config": config_data,
        }

        try:
            result = await make_api_request("POST", "/v1/mcp-server-instances", data)
            name_result = safe_get_field(result, "name")
            id_result = safe_get_field(result, "id")
            click.echo(f"✅ Created MCP instance: {name_result}")
            click.echo(f"   ID: {id_result}")
        except Exception as e:
            click.echo(f"❌ Error creating instance: {e}")

    asyncio.run(_create_instance())


# ============================================================================
# Agent Management Commands
# ============================================================================


@cli.group()
def agent():
    """Agent management commands."""
    pass


@agent.command()
def list():
    """List available agents."""

    async def _list_agents():
        try:
            data = await make_api_request("GET", "/v1/agents")
            if data and hasattr(data, '__iter__') and not isinstance(data, str):
                click.echo("Available Agents:")
                for agent in data:
                    name = safe_get_field(agent, "name")
                    description = safe_get_field(agent, "description")
                    model_id = safe_get_field(agent, "model_id")
                    status = safe_get_field(agent, "status")
                    click.echo(f"  • {name} - {description}")
                    click.echo(f"    Model: {model_id}")
                    click.echo(f"    Status: {status}")
            else:
                click.echo("No agents found")
        except Exception as e:
            click.echo(f"Error listing agents: {e}")

    asyncio.run(_list_agents())


@agent.command()
@click.option("--name", required=True, help="Agent name")
@click.option("--description", required=True, help="Agent description")
@click.option("--instruction", required=True, help="Agent instructions/prompt")
@click.option("--model-id", required=True, help="LLM model instance ID")
@click.option("--planning/--no-planning", default=False, help="Enable planning capabilities")
def create(name: str, description: str, instruction: str, model_id: str, planning: bool):
    """Create a new agent."""

    async def _create_agent():
        data = {
            "name": name,
            "description": description,
            "instruction": instruction,
            "model_id": model_id,
            "planning": planning,
            "tools_config": {"mcp_server_configs": []},
            "events_config": {"events": []},
        }

        try:
            result = await make_api_request("POST", "/v1/agents", data)
            name_result = safe_get_field(result, "name")
            id_result = safe_get_field(result, "id")
            click.echo(f"✅ Created agent: {name_result}")
            click.echo(f"   ID: {id_result}")
        except Exception as e:
            click.echo(f"❌ Error creating agent: {e}")

    asyncio.run(_create_agent())


# ============================================================================
# Task/Chat Commands
# ============================================================================


@cli.group()
def chat():
    """Chat and task communication commands."""
    pass


@chat.command()
@click.option("--agent-id", required=True, help="Agent ID to chat with")
@click.option("--message", required=True, help="Message to send")
@click.option("--session-id", help="Session ID for conversation context")
@click.option("--user-id", help="User ID")
def send(agent_id: str, message: str, session_id: str | None, user_id: str | None):
    """Send a chat message to an agent."""

    async def _send_message():
        data = {
            "content": message,
            "agent_id": agent_id,
            "task_type": "message",
            "session_id": session_id,
            "user_id": user_id,
        }

        try:
            result = await make_api_request("POST", "/v1/chat/messages", data)
            content = safe_get_field(result, "content", "No response")
            session_id_result = safe_get_field(result, "session_id")
            click.echo("Agent Response:")
            click.echo(f"  {content}")
            if session_id_result != "Unknown":
                click.echo(f"Session ID: {session_id_result}")
        except Exception as e:
            click.echo(f"❌ Error sending message: {e}")

    asyncio.run(_send_message())


@chat.command()
@click.option("--agent-id", required=True, help="Agent ID to chat with")
@click.option("--session-id", help="Session ID for conversation context")
def interactive(agent_id: str, session_id: str | None):
    """Start an interactive chat session with an agent."""
    import uuid

    if not session_id:
        session_id = str(uuid.uuid4())

    click.echo(f"Starting interactive chat with agent {agent_id}")
    click.echo(f"Session ID: {session_id}")
    click.echo("Type 'exit' or 'quit' to end the session")
    click.echo("-" * 50)

    async def _interactive_chat():
        while True:
            try:
                message = click.prompt("You", type=str, prompt_suffix="> ")

                if message.lower() in ["exit", "quit"]:
                    click.echo("Goodbye!")
                    break

                data = {
                    "content": message,
                    "agent_id": agent_id,
                    "task_type": "message",
                    "session_id": session_id,
                }

                result = await make_api_request("POST", "/v1/chat/messages", data)
                content = safe_get_field(result, "content", "No response")
                click.echo(f"Agent> {content}")

            except KeyboardInterrupt:
                click.echo("\nGoodbye!")
                break
            except Exception as e:
                click.echo(f"❌ Error: {e}")

    asyncio.run(_interactive_chat())


@chat.command()
@click.option("--session-id", required=True, help="Session ID")
def history(session_id: str):
    """Get chat history for a session."""

    async def _get_history():
        try:
            data = await make_api_request("GET", f"/v1/chat/sessions/{session_id}/history")
            if data:
                click.echo(f"Chat History (Session: {session_id}):")
                for msg in data:
                    role = msg.get("role", "unknown")
                    content = msg.get("content", "")
                    timestamp = msg.get("timestamp", "")
                    click.echo(f"[{timestamp}] {role.capitalize()}: {content}")
            else:
                click.echo("No chat history found")
        except Exception as e:
            click.echo(f"Error getting history: {e}")

    asyncio.run(_get_history())


# ============================================================================
# Task Management Commands
# ============================================================================


@cli.group()
def task():
    """Task management commands."""
    pass


@task.command()
def list():
    """List all tasks."""

    async def _list_tasks():
        try:
            data = await make_api_request("GET", "/v1/tasks")
            if data and hasattr(data, '__iter__') and not isinstance(data, str):
                click.echo("All Tasks:")
                for task in data:
                    task_id = safe_get_field(task, "id")
                    agent_name = safe_get_field(task, "agent_name")
                    description = safe_get_field(task, "description")
                    status = safe_get_field(task, "status")
                    created_at = safe_get_field(task, "created_at")
                    click.echo(f"  • {task_id[:8]}... - {agent_name}")
                    click.echo(f"    Description: {description}")
                    click.echo(f"    Status: {status}")
                    click.echo(f"    Created: {created_at}")
                    click.echo()
            else:
                click.echo("No tasks found")
        except Exception as e:
            click.echo(f"Error listing tasks: {e}")

    asyncio.run(_list_tasks())


@task.command()
@click.option("--agent-id", required=True, help="Agent ID to execute the task")
@click.option("--description", required=True, help="Task description")
@click.option("--parameters", help="Task parameters as JSON string")
@click.option("--user-id", default="cli_user", help="User ID")
@click.option("--stream/--no-stream", default=True, help="Stream task execution events")
def create(agent_id: str, description: str, parameters: str | None, user_id: str, stream: bool):
    """Create and execute a task for an agent."""

    async def _create_task():
        # Parse parameters if provided
        task_params = {}
        if parameters:
            try:
                task_params = json.loads(parameters)
            except json.JSONDecodeError:
                click.echo("❌ Invalid JSON in parameters")
                return

        data = {
            "description": description,
            "parameters": task_params,
            "user_id": user_id,
            "enable_agent_communication": True,
        }

        try:
            if stream:
                # Use streaming endpoint for real-time updates
                click.echo(f"🚀 Creating task for agent {agent_id}")
                click.echo(f"📝 Description: {description}")
                click.echo("📡 Streaming execution events...")
                click.echo("-" * 50)
                
                async with httpx.AsyncClient(timeout=300.0) as client:
                    url = f"http://localhost:8000/v1/agents/{agent_id}/tasks/"
                    
                    async with client.stream("POST", url, json=data) as response:
                        response.raise_for_status()
                        
                        async for line in response.aiter_lines():
                            if line.startswith("data: "):
                                try:
                                    event_data = json.loads(line[6:])  # Remove "data: " prefix
                                    event_type = event_data.get("type", "unknown")
                                    data_content = event_data.get("data", {})
                                    
                                    if event_type == "connected":
                                        click.echo(f"✅ Connected to agent: {data_content.get('agent_name', 'Unknown')}")
                                    elif event_type == "task_created":
                                        task_id = data_content.get("task_id", "unknown")
                                        click.echo(f"📋 Task created: {task_id}")
                                        click.echo(f"   Status: {data_content.get('status', 'unknown')}")
                                    elif event_type == "workflow_started":
                                        click.echo("🔄 Workflow started")
                                    elif event_type == "iteration_started":
                                        iteration = data_content.get("iteration", "unknown")
                                        click.echo(f"🔄 Iteration {iteration} started")
                                    elif event_type == "llm_call_completed":
                                        cost = data_content.get("cost", 0)
                                        click.echo(f"🤖 LLM call completed (cost: ${cost:.4f})")
                                    elif event_type == "tool_call_started":
                                        tool_name = data_content.get("tool_name", "unknown")
                                        click.echo(f"🔧 Tool call started: {tool_name}")
                                    elif event_type == "tool_call_completed":
                                        tool_name = data_content.get("tool_name", "unknown")
                                        success = data_content.get("success", False)
                                        status = "✅" if success else "❌"
                                        click.echo(f"{status} Tool call completed: {tool_name}")
                                    elif event_type == "workflow_completed":
                                        click.echo("🎉 Workflow completed successfully!")
                                        final_response = data_content.get("final_response")
                                        if final_response:
                                            click.echo(f"📄 Final response: {final_response}")
                                        break
                                    elif event_type == "workflow_failed":
                                        click.echo("❌ Workflow failed!")
                                        error = data_content.get("error", "Unknown error")
                                        click.echo(f"   Error: {error}")
                                        break
                                    elif event_type == "error":
                                        click.echo(f"❌ Error: {data_content.get('error', 'Unknown error')}")
                                        break
                                    else:
                                        # Show other events with less formatting
                                        message = data_content.get("message", str(data_content))
                                        click.echo(f"📡 {event_type}: {message}")
                                        
                                except json.JSONDecodeError:
                                    continue  # Skip malformed events
                            
            else:
                # Use regular endpoint
                result = await make_api_request("POST", f"/v1/agents/{agent_id}/tasks/", data)
                task_id = safe_get_field(result, "id")
                status = safe_get_field(result, "status")
                click.echo(f"✅ Created task: {task_id}")
                click.echo(f"   Status: {status}")

        except Exception as e:
            click.echo(f"❌ Error creating task: {e}")

    asyncio.run(_create_task())


if __name__ == "__main__":
    cli()
