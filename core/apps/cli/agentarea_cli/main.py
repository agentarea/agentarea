"""Main CLI entry point for AgentArea CLI."""

import os
import sys
import click

from agentarea_cli.client import AgentAreaClient
from agentarea_cli.config import Config, AuthConfig
from agentarea_cli.exceptions import AgentAreaError
from agentarea_cli.commands.auth import auth
from agentarea_cli.commands.agent import agent
from agentarea_cli.commands.chat import chat
from agentarea_cli.commands.llm import llm
from agentarea_cli.commands.system import system


# Global config instance
config = Config()

@click.group()
@click.option("--api-url", help="AgentArea API URL (overrides stored config)")
@click.option("--debug", is_flag=True, help="Enable debug mode")
@click.option("--agent", help="Agent ID or name for global operations")
@click.pass_context
def cli(ctx, api_url, debug, agent):
    """AgentArea CLI - Command Line Interface for AgentArea."""
    # Initialize configuration
    config = Config()
    auth_config = AuthConfig(config)
    
    # Override API URL if provided
    if api_url:
        auth_config.set_api_url(api_url)
    
    base_url = auth_config.get_api_url()
    
    # Initialize client
    client = AgentAreaClient(base_url=base_url, auth_config=auth_config)
    
    # Store in context for subcommands
    ctx.ensure_object(dict)
    ctx.obj["client"] = client
    ctx.obj["config"] = config
    ctx.obj["auth_config"] = auth_config
    ctx.obj["debug"] = debug
    ctx.obj["global_agent"] = agent


# Top-level task command that uses global --agent option
@cli.command()
@click.argument("task_text")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.option("--stream/--no-stream", default=True, help="Stream response in real-time")
@click.pass_context
def task(ctx, task_text: str, output_format: str, stream: bool):
    """Send a task to an agent (requires --agent option)."""
    from agentarea_cli.client import run_async
    from agentarea_cli.exceptions import AgentAreaAPIError
    
    global_agent = ctx.obj.get("global_agent")
    if not global_agent:
        click.echo("❌ Please specify an agent using --agent option")
        click.echo("   Example: agentarea --agent designer task 'find some good thing'")
        raise click.Abort()
    
    if len(task_text.strip()) < 3:
        click.echo("❌ Task text must be at least 3 characters long")
        raise click.Abort()
    
    async def _send_task():
        client = ctx.obj["client"]
        auth_config = ctx.obj["auth_config"]
        
        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()
        
        # First, try to resolve agent by name if it's not a UUID
        agent_id = global_agent
        if not _is_uuid(global_agent):
            try:
                agents = await client.get("/v1/agents/")
                matching_agents = [a for a in agents if a.get("name", "").lower() == global_agent.lower()]
                if not matching_agents:
                    click.echo(f"❌ No agent found with name '{global_agent}'")
                    raise click.Abort()
                elif len(matching_agents) > 1:
                    click.echo(f"❌ Multiple agents found with name '{global_agent}'. Please use agent ID instead.")
                    raise click.Abort()
                agent_id = matching_agents[0]["id"]
            except AgentAreaAPIError as e:
                click.echo(f"❌ Failed to resolve agent name: {e}")
                raise click.Abort()
        
        data = {
            "description": task_text.strip(),
            "stream": stream
        }
        
        try:
            if stream and output_format == "text":
                click.echo(f"🚀 Sending task to agent '{global_agent}': {task_text}")
                click.echo("📝 Response:")
                click.echo()
                
                # Use streaming method for real-time response
                await client.post_stream(f"/v1/agents/{agent_id}/tasks/", data)
            else:
                result = await client.post(f"/v1/agents/{agent_id}/tasks/", data)
                
                if output_format == "json":
                    import json
                    click.echo(json.dumps(result, indent=2))
                else:
                    click.echo(f"🚀 Task sent to agent '{global_agent}': {task_text}")
                    if "response" in result:
                        click.echo("📝 Response:")
                        click.echo(result["response"])
                    else:
                        click.echo("✅ Task completed successfully")
            
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to send task: {e}")
            raise click.Abort()
    
    run_async(_send_task())


def _is_uuid(value: str) -> bool:
    """Check if a string is a valid UUID."""
    import re
    uuid_pattern = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$', re.IGNORECASE)
    return bool(uuid_pattern.match(value))


# Register command groups
cli.add_command(auth)
cli.add_command(agent)
cli.add_command(chat)
cli.add_command(llm)
cli.add_command(system)


def main():
    """Main entry point with error handling."""
    try:
        cli()
    except KeyboardInterrupt:
        click.echo("\n❌ Operation cancelled by user.", err=True)
        sys.exit(1)
    except AgentAreaError as e:
        click.echo(f"❌ {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"❌ Unexpected error: {e}", err=True)
        # Check if debug mode is enabled via environment variable
        if os.getenv("AGENTAREA_DEBUG", "").lower() in ("true", "1", "yes"):
            import traceback
            traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()