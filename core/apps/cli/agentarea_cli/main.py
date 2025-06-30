"""AgentArea Management CLI - High-level application management."""

import asyncio
import json
import sys
from typing import Any

import click
import httpx


class AgentAreaClient:
    """HTTP client for communicating with AgentArea API."""
    
    def __init__(self, base_url: str = "http://localhost:8000"):
        self.base_url = base_url.rstrip("/")
    
    async def request(self, method: str, endpoint: str, data: dict[str, Any] | None = None) -> dict[str, Any]:
        """Make HTTP request to the API."""
        async with httpx.AsyncClient(timeout=30.0) as client:
            url = f"{self.base_url}{endpoint}"
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
                click.echo(f"❌ Cannot connect to API server at {self.base_url}")
                click.echo("   Make sure the API server is running")
                raise
            except httpx.HTTPStatusError as e:
                click.echo(f"❌ HTTP {e.response.status_code}: {e.response.text}")
                raise
            except Exception as e:
                click.echo(f"❌ Request failed: {e}")
                raise


def safe_get_field(item: Any, field: str, default: str = "Unknown") -> str:
    """Safely get a field from an item."""
    if item is None:
        return default
    if isinstance(item, dict):
        return item.get(field, default)
    if hasattr(item, field):
        return getattr(item, field, default)
    return str(item)


@click.group()
@click.option("--api-url", default="http://localhost:8000", help="API server URL")
@click.pass_context
def cli(ctx, api_url: str):
    """AgentArea Management CLI - High-level application management."""
    ctx.ensure_object(dict)
    ctx.obj['client'] = AgentAreaClient(api_url)


# ============================================================================
# LLM Management Commands
# ============================================================================

@cli.group()
def llm():
    """LLM model and instance management."""
    pass


@llm.command()
@click.pass_context
def models(ctx):
    """List available LLM models."""
    async def _list_models():
        try:
            data = await ctx.obj['client'].request("GET", "/v1/llm-models")
            if data and isinstance(data, list):
                click.echo("📋 Available LLM Models:")
                for model in data:
                    name = safe_get_field(model, "name")
                    provider = safe_get_field(model, "provider")
                    description = safe_get_field(model, "description")
                    click.echo(f"  • {name} ({provider}) - {description}")
            else:
                click.echo("No LLM models found")
        except Exception as e:
            click.echo(f"❌ Failed to list models: {e}")
            sys.exit(1)
    
    asyncio.run(_list_models())


@llm.command()
@click.option("--name", required=True, help="Model name")
@click.option("--description", required=True, help="Model description")
@click.option("--provider", required=True, help="Provider (e.g., openai, anthropic)")
@click.option("--model-type", required=True, help="Model type")
@click.option("--endpoint-url", required=True, help="API endpoint URL")
@click.option("--context-window", default="4096", help="Context window size")
@click.option("--is-public/--no-public", default=False, help="Make model public")
@click.pass_context
def create_model(ctx, name: str, description: str, provider: str, model_type: str, 
                endpoint_url: str, context_window: str, is_public: bool):
    """Create a new LLM model."""
    async def _create_model():
        data = {
            "name": name,
            "description": description,
            "provider": provider,
            "model_type": model_type,
            "endpoint_url": endpoint_url,
            "context_window": int(context_window),
            "is_public": is_public
        }
        
        try:
            result = await ctx.obj['client'].request("POST", "/v1/llm-models", data)
            click.echo(f"✅ Model '{name}' created successfully")
            click.echo(f"   ID: {result.get('id', 'N/A')}")
        except Exception as e:
            click.echo(f"❌ Failed to create model: {e}")
            sys.exit(1)
    
    asyncio.run(_create_model())


# ============================================================================
# Agent Management Commands
# ============================================================================

@cli.group()
def agent():
    """Agent management commands."""
    pass


@agent.command()
@click.pass_context
def list(ctx):
    """List all agents."""
    async def _list_agents():
        try:
            data = await ctx.obj['client'].request("GET", "/v1/agents")
            if data and isinstance(data, list):
                click.echo("🤖 Available Agents:")
                for agent in data:
                    name = safe_get_field(agent, "name")
                    description = safe_get_field(agent, "description")
                    status = safe_get_field(agent, "status", "unknown")
                    click.echo(f"  • {name} - {description} (Status: {status})")
            else:
                click.echo("No agents found")
        except Exception as e:
            click.echo(f"❌ Failed to list agents: {e}")
            sys.exit(1)
    
    asyncio.run(_list_agents())


@agent.command()
@click.option("--name", required=True, help="Agent name")
@click.option("--description", required=True, help="Agent description")
@click.option("--instruction", required=True, help="Agent instructions/prompt")
@click.option("--model-id", required=True, help="LLM model instance ID")
@click.option("--planning/--no-planning", default=False, help="Enable planning")
@click.pass_context
def create(ctx, name: str, description: str, instruction: str, model_id: str, planning: bool):
    """Create a new agent."""
    async def _create_agent():
        data = {
            "name": name,
            "description": description,
            "instruction": instruction,
            "llm_model_instance_id": model_id,
            "planning_enabled": planning
        }
        
        try:
            result = await ctx.obj['client'].request("POST", "/v1/agents", data)
            click.echo(f"✅ Agent '{name}' created successfully")
            click.echo(f"   ID: {result.get('id', 'N/A')}")
        except Exception as e:
            click.echo(f"❌ Failed to create agent: {e}")
            sys.exit(1)
    
    asyncio.run(_create_agent())


# ============================================================================
# System Management Commands
# ============================================================================

@cli.group()
def system():
    """System management commands."""
    pass


@system.command()
@click.pass_context
def status(ctx):
    """Check system status."""
    async def _check_status():
        try:
            # Check API health
            health = await ctx.obj['client'].request("GET", "/health")
            click.echo("🏥 System Status:")
            click.echo(f"   API: ✅ {health.get('status', 'unknown')}")
            click.echo(f"   Version: {health.get('version', 'unknown')}")
            
            # Try to get some basic stats
            try:
                agents = await ctx.obj['client'].request("GET", "/v1/agents")
                models = await ctx.obj['client'].request("GET", "/v1/llm-models")
                click.echo(f"   Agents: {len(agents) if isinstance(agents, list) else 0}")
                click.echo(f"   Models: {len(models) if isinstance(models, list) else 0}")
            except:
                click.echo("   Stats: Unable to retrieve")
                
        except Exception as e:
            click.echo(f"❌ System status check failed: {e}")
            sys.exit(1)
    
    asyncio.run(_check_status())


if __name__ == "__main__":
    cli() 