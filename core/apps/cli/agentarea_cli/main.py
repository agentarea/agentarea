"""Main CLI entry point for AgentArea CLI."""

import os
import sys

import click

from agentarea_cli.client import AgentAreaClient
from agentarea_cli.commands.a2a import a2a
from agentarea_cli.commands.agent import agent
from agentarea_cli.commands.auth import auth
from agentarea_cli.commands.chat import chat
from agentarea_cli.commands.llm import llm
from agentarea_cli.commands.system import system
from agentarea_cli.commands.task import task
from agentarea_cli.config import AuthConfig, Config
from agentarea_cli.exceptions import AgentAreaError

# Global config instance
config = Config()

@click.group()
@click.option("--api-url", help="AgentArea API URL (overrides stored config)")
@click.option("--debug", is_flag=True, help="Enable debug mode")
@click.pass_context
def cli(ctx, api_url, debug):
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


# Register command groups
cli.add_command(a2a)
cli.add_command(auth)
cli.add_command(agent)
cli.add_command(chat)
cli.add_command(llm)
cli.add_command(system)
cli.add_command(task)


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
