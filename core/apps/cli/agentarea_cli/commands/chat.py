"""Chat commands for AgentArea CLI."""

import json
from typing import TYPE_CHECKING

import click

from agentarea_cli.client import run_async
from agentarea_cli.exceptions import APIError as AgentAreaAPIError
from agentarea_cli.exceptions import AuthenticationError
from agentarea_cli.utils import format_table, safe_get_field

if TYPE_CHECKING:
    from agentarea_cli.client import AgentAreaClient
    from agentarea_cli.config import AuthConfig


@click.group()
def chat():
    """Chat with agents."""
    pass


@chat.command()
@click.argument("agent_id")
@click.option("--message", "-m", help="Single message to send")
@click.option("--session-id", help="Chat session ID (optional)")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.pass_context
def send(ctx, agent_id: str, message: str | None, session_id: str | None, output_format: str):
    """Send a message to an agent."""

    async def _send():
        client: AgentAreaClient = ctx.obj["client"]
        auth_config: AuthConfig = ctx.obj["auth_config"]

        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()

        try:
            # If no message provided, enter interactive mode
            if not message:
                await _interactive_chat(client, agent_id, session_id, output_format)
            else:
                await _single_message(client, agent_id, message, session_id, output_format)

        except AuthenticationError:
            click.echo("❌ Authentication failed. Please login again with 'agentarea auth login'")
            raise click.Abort()
        except AgentAreaAPIError as e:
            click.echo(f"❌ Chat failed: {e}")
            raise click.Abort()

    run_async(_send())


async def _interactive_chat(
    client: "AgentAreaClient",
    agent_id: str,
    session_id: str | None,
    output_format: str
):
    """Handle interactive chat mode."""
    click.echo(f"💬 Starting chat with agent {agent_id}")
    click.echo("   Commands:")
    click.echo("   - Type 'exit' or 'quit' to end the conversation")
    click.echo("   - Type 'clear' to start a new session")
    click.echo("   - Type 'help' to show this help")
    click.echo("   - Type 'status' to show session info")
    click.echo()

    current_session_id = session_id
    message_count = 0

    while True:
        try:
            user_input = input("You: ").strip()

            if user_input.lower() in ['exit', 'quit']:
                click.echo("👋 Goodbye!")
                break

            if user_input.lower() == 'clear':
                current_session_id = None
                message_count = 0
                click.echo("🔄 Starting new session")
                continue

            if user_input.lower() == 'help':
                click.echo("Available commands:")
                click.echo("   exit, quit - End conversation")
                click.echo("   clear      - Start new session")
                click.echo("   help       - Show this help")
                click.echo("   status     - Show session info")
                continue

            if user_input.lower() == 'status':
                click.echo(f"Session ID: {current_session_id or 'None (new session)'}")
                click.echo(f"Messages sent: {message_count}")
                continue

            if not user_input:
                continue

            # Send message
            result = await _send_message(client, agent_id, user_input, current_session_id)

            # Store session ID for future messages
            if not current_session_id and "session_id" in result:
                current_session_id = result["session_id"]
                click.echo(f"📝 Session started: {current_session_id}")

            message_count += 1

            # Display response
            _display_response(result, output_format)

        except KeyboardInterrupt:
            click.echo("\n👋 Goodbye!")
            break
        except EOFError:
            click.echo("\n👋 Goodbye!")
            break
        except Exception as e:
            click.echo(f"❌ Error: {e}")
            continue


async def _single_message(
    client: "AgentAreaClient",
    agent_id: str,
    message: str,
    session_id: str | None,
    output_format: str
):
    """Handle single message mode."""
    result = await _send_message(client, agent_id, message, session_id)

    click.echo(f"✅ Message sent to agent {agent_id}")

    if output_format == "json":
        click.echo(json.dumps(result, indent=2))
    else:
        if "task_id" in result:
            click.echo(f"   Task ID: {result['task_id']}")
        if "session_id" in result:
            click.echo(f"   Session ID: {result['session_id']}")
        if "response" in result:
            click.echo(f"   Response: {result['response']}")


async def _send_message(
    client: "AgentAreaClient",
    agent_id: str,
    message: str,
    session_id: str | None
) -> dict:
    """Send a message to an agent."""
    payload = {
        "content": message,
        "agent_id": agent_id
    }

    if session_id:
        payload["session_id"] = session_id

    return await client.post("/api/v1/chat/messages", payload)


def _display_response(result: dict, output_format: str):
    """Display chat response."""
    if output_format == "json":
        click.echo(json.dumps(result, indent=2))
        return

    # Text format
    if "task_id" in result:
        click.echo(f"🤖 Agent: Task started (ID: {result['task_id']})")
        if "response" in result:
            click.echo(f"    {result['response']}")
    else:
        response = result.get('response', 'No response')
        click.echo(f"🤖 Agent: {response}")


@chat.command()
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
@click.pass_context
def agents(ctx, output_format: str):
    """List available chat agents."""

    async def _list_agents():
        client: AgentAreaClient = ctx.obj["client"]

        try:
            result = await client.get("/api/v1/chat/agents")

            agents_list = result.get("agents", [])
            if not agents_list:
                click.echo("📭 No chat agents available")
                return

            if output_format == "json":
                click.echo(json.dumps(agents_list, indent=2))
                return

            # Table format
            click.echo("🤖 Available Chat Agents:")
            click.echo()

            headers = ["ID", "Name", "Description", "Status"]
            rows = []

            for agent in agents_list:
                rows.append([
                    safe_get_field(agent, "id", "Unknown"),
                    safe_get_field(agent, "name", "Unknown"),
                    safe_get_field(agent, "description", "No description")[:50] + "..." if len(safe_get_field(agent, "description", "")) > 50 else safe_get_field(agent, "description", "No description"),
                    safe_get_field(agent, "status", "Unknown")
                ])

            click.echo(format_table(headers, rows))

        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to list chat agents: {e}")
            raise click.Abort()

    run_async(_list_agents())


@chat.command()
@click.option("--session-id", help="Session ID to get history for")
@click.option("--agent-id", help="Agent ID to filter by")
@click.option("--limit", default=50, help="Maximum number of messages to retrieve")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.pass_context
def history(ctx, session_id: str | None, agent_id: str | None, limit: int, output_format: str):
    """Show chat history."""

    async def _get_history():
        client: AgentAreaClient = ctx.obj["client"]

        params = {"limit": limit}
        if session_id:
            params["session_id"] = session_id
        if agent_id:
            params["agent_id"] = agent_id

        try:
            result = await client.get("/api/v1/chat/history", params=params)

            messages = result.get("messages", [])
            if not messages:
                click.echo("📭 No chat history found")
                return

            if output_format == "json":
                click.echo(json.dumps(messages, indent=2))
                return

            # Text format
            click.echo(f"💬 Chat History ({len(messages)} messages):")
            click.echo()

            for msg in messages:
                timestamp = msg.get('timestamp', 'Unknown time')
                sender = msg.get('sender', 'Unknown')
                content = msg.get('content', 'No content')

                click.echo(f"[{timestamp}] {sender}: {content}")

        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to get chat history: {e}")
            raise click.Abort()

    run_async(_get_history())


@chat.command()
@click.option("--session-id", help="Session ID to clear (if not provided, clears all sessions)")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def clear(ctx, session_id: str | None, force: bool):
    """Clear chat history."""
    if not force:
        if session_id:
            message = f"Are you sure you want to clear session '{session_id}'?"
        else:
            message = "Are you sure you want to clear ALL chat history?"

        if not click.confirm(message):
            click.echo("❌ Operation cancelled")
            return

    async def _clear_history():
        client: AgentAreaClient = ctx.obj["client"]

        endpoint = "/api/v1/chat/history"
        if session_id:
            endpoint += f"/{session_id}"

        try:
            await client.delete(endpoint)

            if session_id:
                click.echo(f"✅ Session '{session_id}' cleared successfully")
            else:
                click.echo("✅ All chat history cleared successfully")

        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to clear chat history: {e}")
            raise click.Abort()

    run_async(_clear_history())
