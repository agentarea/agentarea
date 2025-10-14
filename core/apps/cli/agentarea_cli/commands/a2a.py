"""A2A (Agent-to-Agent) CLI commands for testing and interacting with agents."""

import asyncio
import json
import uuid

import aiohttp
import click


@click.group()
def a2a():
    """A2A (Agent-to-Agent) protocol commands."""
    pass


@a2a.command()
@click.argument("agent_id")
@click.option("--base-url", default="http://localhost:8000", help="Base URL of the AgentArea API")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "table"]),
    default="table",
    help="Output format",
)
@click.option("--token", help="Bearer token for authentication")
@click.option("--api-key", help="API key for authentication")
async def discover(
    agent_id: str, base_url: str, output_format: str, token: str, api_key: str
):
    """Discover an agent's capabilities via A2A well-known endpoint."""
    try:
        url = f"{base_url}/v1/agents/{agent_id}/.well-known/a2a-info.json"

        # Prepare headers for authentication
        headers = {}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        elif api_key:
            headers["X-API-Key"] = api_key

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    agent_card = await response.json()

                    if output_format == "json":
                        click.echo(json.dumps(agent_card, indent=2))
                    else:
                        # Table format
                        click.echo(f"🤖 Agent Discovery: {agent_id}")
                        click.echo("=" * 50)
                        click.echo(f"Name: {agent_card.get('name', 'Unknown')}")
                        click.echo(
                            f"Description: {agent_card.get('description', 'No description')}"
                        )
                        click.echo(f"URL: {agent_card.get('url', 'No URL')}")
                        click.echo(f"Version: {agent_card.get('version', 'Unknown')}")

                        # Capabilities
                        capabilities = agent_card.get("capabilities", {})
                        click.echo("\n📋 Capabilities:")
                        click.echo(f"  Streaming: {capabilities.get('streaming', False)}")
                        click.echo(
                            f"  Push Notifications: {capabilities.get('push_notifications', False)}"
                        )
                        click.echo(
                            f"  State History: {capabilities.get('state_transition_history', False)}"
                        )

                        # Skills
                        skills = agent_card.get("skills", [])
                        click.echo(f"\n🛠️  Skills ({len(skills)}):")
                        for skill in skills:
                            click.echo(
                                f"  • {skill.get('name', 'Unknown')} ({skill.get('id', 'no-id')})"
                            )
                            click.echo(f"    {skill.get('description', 'No description')}")
                            click.echo(f"    Input: {', '.join(skill.get('input_modes', []))}")
                            click.echo(f"    Output: {', '.join(skill.get('output_modes', []))}")
                            click.echo()

                        # Provider
                        provider = agent_card.get("provider", {})
                        click.echo(f"🏢 Provider: {provider.get('organization', 'Unknown')}")
                        if provider.get("url"):
                            click.echo(f"   URL: {provider.get('url')}")

                elif response.status == 404:
                    click.echo(f"❌ Agent {agent_id} not found", err=True)
                else:
                    error_text = await response.text()
                    click.echo(f"❌ Error {response.status}: {error_text}", err=True)

    except Exception as e:
        click.echo(f"❌ Failed to discover agent: {e}", err=True)


@a2a.command()
@click.argument("agent_id")
@click.argument("message")
@click.option("--base-url", default="http://localhost:8000", help="Base URL of the AgentArea API")
@click.option(
    "--method",
    type=click.Choice(["message/send", "tasks/send"]),
    default="message/send",
    help="A2A method to use",
)
@click.option("--stream", is_flag=True, help="Use streaming (message/stream)")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "table"]),
    default="table",
    help="Output format",
)
async def send(
    agent_id: str, message: str, base_url: str, method: str, stream: bool, output_format: str
):
    """Send a message to an agent via A2A protocol."""
    try:
        url = f"{base_url}/v1/agents/{agent_id}/a2a/rpc"

        # Use streaming method if requested
        if stream:
            method = "message/stream"

        # Prepare JSON-RPC request
        request_data = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": method,
            "params": {"message": {"role": "user", "parts": [{"text": message}]}},
        }

        async with aiohttp.ClientSession() as session:
            if stream:
                # Handle streaming response
                async with session.post(url, json=request_data) as response:
                    if response.status == 200:
                        click.echo(f"🔄 Streaming response from agent {agent_id}:")
                        click.echo("=" * 50)

                        async for line in response.content:
                            line_str = line.decode("utf-8").strip()
                            if line_str.startswith("data: "):
                                data_str = line_str[6:]  # Remove 'data: ' prefix
                                if data_str == "[DONE]":
                                    click.echo("\n✅ Stream completed")
                                    break

                                try:
                                    event_data = json.loads(data_str)
                                    event_type = event_data.get("event", "unknown")

                                    if output_format == "json":
                                        click.echo(json.dumps(event_data, indent=2))
                                    else:
                                        if event_type == "task_created":
                                            click.echo(
                                                f"📝 Task created: {event_data.get('task_id')}"
                                            )
                                        elif event_type in [
                                            "task_completed",
                                            "workflow.task_completed",
                                        ]:
                                            click.echo("✅ Task completed")
                                        elif event_type in ["task_failed", "workflow.task_failed"]:
                                            click.echo("❌ Task failed")
                                        else:
                                            click.echo(
                                                f"📡 {event_type}: {event_data.get('data', {})}"
                                            )

                                except json.JSONDecodeError:
                                    click.echo(f"📡 {data_str}")
                    else:
                        error_text = await response.text()
                        click.echo(f"❌ Error {response.status}: {error_text}", err=True)
            else:
                # Handle regular JSON-RPC response
                async with session.post(url, json=request_data) as response:
                    response_data = await response.json()

                    if response.status == 200:
                        if output_format == "json":
                            click.echo(json.dumps(response_data, indent=2))
                        else:
                            if "result" in response_data:
                                result = response_data["result"]
                                click.echo(f"✅ Message sent to agent {agent_id}")
                                click.echo(f"📝 Task ID: {result.get('id')}")
                                click.echo(
                                    f"📊 Status: {result.get('status', {}).get('state', 'unknown')}"
                                )
                            elif "error" in response_data:
                                error = response_data["error"]
                                click.echo(
                                    f"❌ Error {error.get('code')}: {error.get('message')}",
                                    err=True,
                                )
                    else:
                        click.echo(
                            f"❌ HTTP Error {response.status}: {await response.text()}", err=True
                        )

    except Exception as e:
        click.echo(f"❌ Failed to send message: {e}", err=True)


@a2a.command()
@click.argument("agent_id")
@click.argument("task_id")
@click.option("--base-url", default="http://localhost:8000", help="Base URL of the AgentArea API")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "table"]),
    default="table",
    help="Output format",
)
async def get_task(agent_id: str, task_id: str, base_url: str, output_format: str):
    """Get task status via A2A protocol."""
    try:
        url = f"{base_url}/v1/agents/{agent_id}/a2a/rpc"

        request_data = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "tasks/get",
            "params": {"id": task_id},
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=request_data) as response:
                response_data = await response.json()

                if response.status == 200:
                    if output_format == "json":
                        click.echo(json.dumps(response_data, indent=2))
                    else:
                        if "result" in response_data:
                            result = response_data["result"]
                            click.echo(f"📋 Task Status: {task_id}")
                            click.echo("=" * 50)
                            click.echo(
                                f"Status: {result.get('status', {}).get('state', 'unknown')}"
                            )
                            click.echo(
                                f"Message: {result.get('status', {}).get('message', 'No message')}"
                            )

                            # Show artifacts if available
                            artifacts = result.get("artifacts", [])
                            if artifacts:
                                click.echo(f"\n📎 Artifacts ({len(artifacts)}):")
                                for artifact in artifacts:
                                    click.echo(f"  • {artifact}")
                        elif "error" in response_data:
                            error = response_data["error"]
                            click.echo(
                                f"❌ Error {error.get('code')}: {error.get('message')}", err=True
                            )
                else:
                    click.echo(
                        f"❌ HTTP Error {response.status}: {await response.text()}", err=True
                    )

    except Exception as e:
        click.echo(f"❌ Failed to get task: {e}", err=True)


@a2a.command()
@click.option("--base-url", default="http://localhost:8000", help="Base URL of the AgentArea API")
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["json", "table"]),
    default="table",
    help="Output format",
)
async def list_agents(base_url: str, output_format: str):
    """List available agents for A2A communication."""
    try:
        url = f"{base_url}/v1/agents"

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    agents_data = await response.json()
                    agents = agents_data.get("agents", [])

                    if output_format == "json":
                        click.echo(json.dumps(agents, indent=2))
                    else:
                        click.echo(f"🤖 Available Agents ({len(agents)}):")
                        click.echo("=" * 50)

                        for agent in agents:
                            click.echo(f"• {agent.get('name', 'Unknown')} ({agent.get('id')})")
                            click.echo(f"  Status: {agent.get('status', 'unknown')}")
                            click.echo(f"  Model: {agent.get('model_id', 'unknown')}")
                            if agent.get("description"):
                                click.echo(f"  Description: {agent.get('description')}")
                            click.echo()

                        if agents:
                            click.echo(
                                "💡 Use 'agentarea a2a discover <agent_id>' to get A2A capabilities"
                            )
                        else:
                            click.echo("No agents found. Create an agent first.")
                else:
                    error_text = await response.text()
                    click.echo(f"❌ Error {response.status}: {error_text}", err=True)

    except Exception as e:
        click.echo(f"❌ Failed to list agents: {e}", err=True)


# Convert async commands to sync for Click
def make_sync(async_func):
    def sync_func(*args, **kwargs):
        return asyncio.run(async_func(*args, **kwargs))

    return sync_func


# Apply sync wrapper to all commands
discover.callback = make_sync(discover.callback)
send.callback = make_sync(send.callback)
get_task.callback = make_sync(get_task.callback)
list_agents.callback = make_sync(list_agents.callback)
