"""Agent management commands for AgentArea CLI."""

from typing import TYPE_CHECKING

import click

from agentarea_cli.client import run_async
from agentarea_cli.exceptions import AgentAreaAPIError
from agentarea_cli.utils import format_table, safe_get_field

if TYPE_CHECKING:
    from agentarea_cli.client import AgentAreaClient


@click.group()
def agent():
    """Agent management commands."""
    pass


@agent.command()
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
@click.pass_context
def list(ctx, output_format: str):
    """List all agents."""
    
    async def _list_agents():
        client: "AgentAreaClient" = ctx.obj["client"]
        
        try:
            data = await client.get("/v1/agents")
            
            if not data or not isinstance(data, list):
                click.echo("📭 No agents found")
                return
            
            if output_format == "json":
                import json
                click.echo(json.dumps(data, indent=2))
                return
            
            # Table format
            click.echo("🤖 Available Agents:")
            click.echo()
            
            headers = ["ID", "Name", "Description", "Status", "Model"]
            rows = []
            
            for agent in data:
                rows.append([
                    safe_get_field(agent, "id", "N/A"),
                    safe_get_field(agent, "name"),
                    safe_get_field(agent, "description", "No description")[:50] + "..." if len(safe_get_field(agent, "description", "")) > 50 else safe_get_field(agent, "description", "No description"),
                    safe_get_field(agent, "status", "unknown"),
                    safe_get_field(agent, "llm_model_instance_id", "N/A")
                ])
            
            click.echo(format_table(headers, rows))
            
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to list agents: {e}")
            raise click.Abort()
    
    run_async(_list_agents())


@agent.command()
@click.option("--name", required=True, help="Agent name")
@click.option("--description", required=True, help="Agent description")
@click.option("--instruction", required=True, help="Agent instructions/prompt")
@click.option("--model-id", required=True, help="LLM model instance ID")
@click.option("--planning/--no-planning", default=False, help="Enable planning")
@click.option("--public/--private", default=False, help="Make agent public")
@click.pass_context
def create(ctx, name: str, description: str, instruction: str, model_id: str, planning: bool, public: bool):
    """Create a new agent."""
    
    # Validate inputs
    if len(name.strip()) < 2:
        click.echo("❌ Agent name must be at least 2 characters long")
        raise click.Abort()
    
    if len(description.strip()) < 10:
        click.echo("❌ Agent description must be at least 10 characters long")
        raise click.Abort()
    
    if len(instruction.strip()) < 20:
        click.echo("❌ Agent instruction must be at least 20 characters long")
        raise click.Abort()
    
    async def _create_agent():
        client: "AgentAreaClient" = ctx.obj["client"]
        
        data = {
            "name": name.strip(),
            "description": description.strip(),
            "instruction": instruction.strip(),
            "llm_model_instance_id": model_id,
            "planning_enabled": planning,
            "is_public": public
        }
        
        try:
            result = await client.post("/v1/agents", data)
            click.echo(f"✅ Agent '{name}' created successfully")
            click.echo(f"   ID: {result.get('id', 'N/A')}")
            click.echo(f"   Status: {result.get('status', 'Unknown')}")
            
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to create agent: {e}")
            raise click.Abort()
    
    run_async(_create_agent())


@agent.command()
@click.argument("agent_id")
@click.pass_context
def show(ctx, agent_id: str):
    """Show detailed information about an agent."""
    
    async def _show_agent():
        client: "AgentAreaClient" = ctx.obj["client"]
        
        try:
            agent = await client.get(f"/v1/agents/{agent_id}")
            
            click.echo(f"🤖 Agent Details:")
            click.echo(f"   ID: {agent.get('id', 'N/A')}")
            click.echo(f"   Name: {agent.get('name', 'Unknown')}")
            click.echo(f"   Description: {agent.get('description', 'No description')}")
            click.echo(f"   Status: {agent.get('status', 'Unknown')}")
            click.echo(f"   Model ID: {agent.get('llm_model_instance_id', 'N/A')}")
            click.echo(f"   Planning: {'Enabled' if agent.get('planning_enabled') else 'Disabled'}")
            click.echo(f"   Public: {'Yes' if agent.get('is_public') else 'No'}")
            click.echo(f"   Created: {agent.get('created_at', 'Unknown')}")
            click.echo(f"   Updated: {agent.get('updated_at', 'Unknown')}")
            
            if instruction := agent.get('instruction'):
                click.echo(f"\n📝 Instructions:")
                click.echo(f"   {instruction}")
            
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to get agent details: {e}")
            raise click.Abort()
    
    run_async(_show_agent())


@agent.command()
@click.argument("agent_id")
@click.option("--name", help="Update agent name")
@click.option("--description", help="Update agent description")
@click.option("--instruction", help="Update agent instructions")
@click.option("--planning/--no-planning", help="Enable/disable planning")
@click.option("--public/--private", help="Make agent public/private")
@click.pass_context
def update(ctx, agent_id: str, name: str, description: str, instruction: str, planning: bool, public: bool):
    """Update an existing agent."""
    
    # Build update data with only provided fields
    update_data = {}
    
    if name is not None:
        if len(name.strip()) < 2:
            click.echo("❌ Agent name must be at least 2 characters long")
            raise click.Abort()
        update_data["name"] = name.strip()
    
    if description is not None:
        if len(description.strip()) < 10:
            click.echo("❌ Agent description must be at least 10 characters long")
            raise click.Abort()
        update_data["description"] = description.strip()
    
    if instruction is not None:
        if len(instruction.strip()) < 20:
            click.echo("❌ Agent instruction must be at least 20 characters long")
            raise click.Abort()
        update_data["instruction"] = instruction.strip()
    
    if planning is not None:
        update_data["planning_enabled"] = planning
    
    if public is not None:
        update_data["is_public"] = public
    
    if not update_data:
        click.echo("❌ No update fields provided")
        raise click.Abort()
    
    async def _update_agent():
        client: "AgentAreaClient" = ctx.obj["client"]
        
        try:
            result = await client.patch(f"/v1/agents/{agent_id}", update_data)
            click.echo(f"✅ Agent '{agent_id}' updated successfully")
            
            if updated_name := result.get('name'):
                click.echo(f"   Name: {updated_name}")
            
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to update agent: {e}")
            raise click.Abort()
    
    run_async(_update_agent())


@agent.command()
@click.argument("agent_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def delete(ctx, agent_id: str, force: bool):
    """Delete an agent."""
    
    if not force:
        if not click.confirm(f"Are you sure you want to delete agent '{agent_id}'?"):
            click.echo("❌ Operation cancelled")
            return
    
    async def _delete_agent():
        client: "AgentAreaClient" = ctx.obj["client"]
        
        try:
            await client.delete(f"/v1/agents/{agent_id}")
            click.echo(f"✅ Agent '{agent_id}' deleted successfully")
            
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to delete agent: {e}")
            raise click.Abort()
    
    run_async(_delete_agent())
