"""LLM commands for AgentArea CLI."""

import json
from typing import TYPE_CHECKING, Optional

import click

from agentarea_cli.client import run_async
from agentarea_cli.exceptions import AgentAreaAPIError, AuthenticationError, ValidationError
from agentarea_cli.utils import format_table, safe_get_field, validate_required_field

if TYPE_CHECKING:
    from agentarea_cli.client import AgentAreaClient
    from agentarea_cli.config import AuthConfig


@click.group()
def llm():
    """Manage LLM models."""
    pass


@llm.command()
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
@click.option("--provider", help="Filter by provider")
@click.option("--status", help="Filter by status")
@click.pass_context
def list(ctx, output_format: str, provider: Optional[str], status: Optional[str]):
    """List available LLM models."""
    
    async def _list_models():
        client: "AgentAreaClient" = ctx.obj["client"]
        
        params = {}
        if provider:
            params["provider"] = provider
        if status:
            params["status"] = status
        
        try:
            result = await client.get("/api/v1/llm/models", params=params)
            
            models = result.get("models", [])
            if not models:
                click.echo("📭 No LLM models found")
                return
            
            if output_format == "json":
                click.echo(json.dumps(models, indent=2))
                return
            
            # Table format
            click.echo("🤖 Available LLM Models:")
            click.echo()
            
            headers = ["ID", "Name", "Provider", "Type", "Status", "Created"]
            rows = []
            
            for model in models:
                rows.append([
                    safe_get_field(model, "id", "Unknown"),
                    safe_get_field(model, "name", "Unknown"),
                    safe_get_field(model, "provider", "Unknown"),
                    safe_get_field(model, "model_type", "Unknown"),
                    safe_get_field(model, "status", "Unknown"),
                    safe_get_field(model, "created_at", "Unknown")[:19] if safe_get_field(model, "created_at") else "Unknown"
                ])
            
            click.echo(format_table(headers, rows))
            
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to list models: {e}")
            raise click.Abort()
    
    run_async(_list_models())


@llm.command()
@click.option("--name", required=True, help="Model name")
@click.option("--provider", required=True, help="Model provider (e.g., openai, anthropic, local)")
@click.option("--model-type", required=True, help="Model type (e.g., chat, completion, embedding)")
@click.option("--config", help="Model configuration as JSON string")
@click.option("--description", help="Model description")
@click.option("--api-key", help="API key for the model (if required)")
@click.option("--base-url", help="Base URL for the model API")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.pass_context
def create(ctx, name: str, provider: str, model_type: str, config: Optional[str], 
          description: Optional[str], api_key: Optional[str], base_url: Optional[str], 
          output_format: str):
    """Create a new LLM model."""
    
    async def _create_model():
        client: "AgentAreaClient" = ctx.obj["client"]
        auth_config: "AuthConfig" = ctx.obj["auth_config"]
        
        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()
        
        try:
            # Validate inputs
            validate_required_field(name, "name")
            validate_required_field(provider, "provider")
            validate_required_field(model_type, "model_type")
            
            # Parse config if provided
            model_config = {}
            if config:
                try:
                    model_config = json.loads(config)
                except json.JSONDecodeError as e:
                    raise ValidationError(f"Invalid JSON in config: {e}")
            
            # Build payload
            payload = {
                "name": name,
                "provider": provider,
                "model_type": model_type,
                "config": model_config
            }
            
            if description:
                payload["description"] = description
            if api_key:
                payload["api_key"] = api_key
            if base_url:
                payload["base_url"] = base_url
            
            result = await client.post("/api/v1/llm/models", payload)
            
            if output_format == "json":
                click.echo(json.dumps(result, indent=2))
            else:
                click.echo(f"✅ Model '{name}' created successfully")
                click.echo(f"   ID: {result.get('id', 'Unknown')}")
                click.echo(f"   Provider: {provider}")
                click.echo(f"   Type: {model_type}")
                if description:
                    click.echo(f"   Description: {description}")
            
        except ValidationError as e:
            click.echo(f"❌ Validation error: {e}")
            raise click.Abort()
        except AuthenticationError:
            click.echo("❌ Authentication failed. Please login again with 'agentarea auth login'")
            raise click.Abort()
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to create model: {e}")
            raise click.Abort()
    
    run_async(_create_model())


@llm.command()
@click.argument("model_id")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.pass_context
def show(ctx, model_id: str, output_format: str):
    """Show detailed information about a model."""
    
    async def _show_model():
        client: "AgentAreaClient" = ctx.obj["client"]
        
        try:
            result = await client.get(f"/api/v1/llm/models/{model_id}")
            
            if output_format == "json":
                click.echo(json.dumps(result, indent=2))
                return
            
            # Text format
            click.echo(f"🤖 Model Details:")
            click.echo(f"   ID: {safe_get_field(result, 'id', 'Unknown')}")
            click.echo(f"   Name: {safe_get_field(result, 'name', 'Unknown')}")
            click.echo(f"   Provider: {safe_get_field(result, 'provider', 'Unknown')}")
            click.echo(f"   Type: {safe_get_field(result, 'model_type', 'Unknown')}")
            click.echo(f"   Status: {safe_get_field(result, 'status', 'Unknown')}")
            
            if result.get("description"):
                click.echo(f"   Description: {result['description']}")
            
            if result.get("base_url"):
                click.echo(f"   Base URL: {result['base_url']}")
            
            if result.get("config"):
                click.echo(f"   Configuration:")
                for key, value in result["config"].items():
                    click.echo(f"     {key}: {value}")
            
            click.echo(f"   Created: {safe_get_field(result, 'created_at', 'Unknown')}")
            click.echo(f"   Updated: {safe_get_field(result, 'updated_at', 'Unknown')}")
            
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to get model details: {e}")
            raise click.Abort()
    
    run_async(_show_model())


@llm.command()
@click.argument("model_id")
@click.option("--name", help="New model name")
@click.option("--description", help="New model description")
@click.option("--config", help="New model configuration as JSON string")
@click.option("--api-key", help="New API key")
@click.option("--base-url", help="New base URL")
@click.option("--status", help="New status")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.pass_context
def update(ctx, model_id: str, name: Optional[str], description: Optional[str], 
          config: Optional[str], api_key: Optional[str], base_url: Optional[str], 
          status: Optional[str], output_format: str):
    """Update an existing model."""
    
    async def _update_model():
        client: "AgentAreaClient" = ctx.obj["client"]
        auth_config: "AuthConfig" = ctx.obj["auth_config"]
        
        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()
        
        try:
            # Build payload with only provided fields
            payload = {}
            
            if name:
                payload["name"] = name
            if description is not None:  # Allow empty string
                payload["description"] = description
            if api_key is not None:  # Allow empty string
                payload["api_key"] = api_key
            if base_url is not None:  # Allow empty string
                payload["base_url"] = base_url
            if status:
                payload["status"] = status
            
            if config:
                try:
                    payload["config"] = json.loads(config)
                except json.JSONDecodeError as e:
                    raise ValidationError(f"Invalid JSON in config: {e}")
            
            if not payload:
                click.echo("❌ No fields provided to update")
                raise click.Abort()
            
            result = await client.put(f"/api/v1/llm/models/{model_id}", payload)
            
            if output_format == "json":
                click.echo(json.dumps(result, indent=2))
            else:
                click.echo(f"✅ Model '{model_id}' updated successfully")
                if name:
                    click.echo(f"   New name: {name}")
                if description is not None:
                    click.echo(f"   New description: {description}")
                if status:
                    click.echo(f"   New status: {status}")
            
        except ValidationError as e:
            click.echo(f"❌ Validation error: {e}")
            raise click.Abort()
        except AuthenticationError:
            click.echo("❌ Authentication failed. Please login again with 'agentarea auth login'")
            raise click.Abort()
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to update model: {e}")
            raise click.Abort()
    
    run_async(_update_model())


@llm.command()
@click.argument("model_id")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def delete(ctx, model_id: str, force: bool):
    """Delete a model."""
    
    if not force:
        if not click.confirm(f"Are you sure you want to delete model '{model_id}'?"):
            click.echo("❌ Operation cancelled")
            return
    
    async def _delete_model():
        client: "AgentAreaClient" = ctx.obj["client"]
        auth_config: "AuthConfig" = ctx.obj["auth_config"]
        
        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()
        
        try:
            await client.delete(f"/api/v1/llm/models/{model_id}")
            click.echo(f"✅ Model '{model_id}' deleted successfully")
            
        except AuthenticationError:
            click.echo("❌ Authentication failed. Please login again with 'agentarea auth login'")
            raise click.Abort()
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to delete model: {e}")
            raise click.Abort()
    
    run_async(_delete_model())


@llm.command()
@click.argument("model_id")
@click.option("--prompt", required=True, help="Test prompt to send to the model")
@click.option("--max-tokens", type=int, help="Maximum tokens to generate")
@click.option("--temperature", type=float, help="Temperature for generation")
@click.option("--format", "output_format", type=click.Choice(["text", "json"]), default="text", help="Output format")
@click.pass_context
def test(ctx, model_id: str, prompt: str, max_tokens: Optional[int], 
        temperature: Optional[float], output_format: str):
    """Test a model with a prompt."""
    
    async def _test_model():
        client: "AgentAreaClient" = ctx.obj["client"]
        auth_config: "AuthConfig" = ctx.obj["auth_config"]
        
        # Check authentication
        if not auth_config.is_authenticated():
            click.echo("❌ Please login first with 'agentarea auth login'")
            raise click.Abort()
        
        try:
            payload = {
                "prompt": prompt
            }
            
            if max_tokens:
                payload["max_tokens"] = max_tokens
            if temperature is not None:
                payload["temperature"] = temperature
            
            result = await client.post(f"/api/v1/llm/models/{model_id}/test", payload)
            
            if output_format == "json":
                click.echo(json.dumps(result, indent=2))
            else:
                click.echo(f"🧪 Test Results for Model '{model_id}':")
                click.echo(f"   Prompt: {prompt}")
                click.echo(f"   Response: {result.get('response', 'No response')}")
                
                if "usage" in result:
                    usage = result["usage"]
                    click.echo(f"   Usage:")
                    click.echo(f"     Prompt tokens: {usage.get('prompt_tokens', 'Unknown')}")
                    click.echo(f"     Completion tokens: {usage.get('completion_tokens', 'Unknown')}")
                    click.echo(f"     Total tokens: {usage.get('total_tokens', 'Unknown')}")
                
                if "latency" in result:
                    click.echo(f"   Latency: {result['latency']}ms")
            
        except AuthenticationError:
            click.echo("❌ Authentication failed. Please login again with 'agentarea auth login'")
            raise click.Abort()
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to test model: {e}")
            raise click.Abort()
    
    run_async(_test_model())


@llm.command()
@click.option("--format", "output_format", type=click.Choice(["table", "json"]), default="table", help="Output format")
@click.pass_context
def providers(ctx, output_format: str):
    """List available LLM providers."""
    
    async def _list_providers():
        client: "AgentAreaClient" = ctx.obj["client"]
        
        try:
            result = await client.get("/api/v1/llm/providers")
            
            providers = result.get("providers", [])
            if not providers:
                click.echo("📭 No LLM providers available")
                return
            
            if output_format == "json":
                click.echo(json.dumps(providers, indent=2))
                return
            
            # Table format
            click.echo("🏢 Available LLM Providers:")
            click.echo()
            
            headers = ["Name", "Description", "Supported Types", "Status"]
            rows = []
            
            for provider in providers:
                supported_types = ", ".join(provider.get("supported_types", []))
                rows.append([
                    safe_get_field(provider, "name", "Unknown"),
                    safe_get_field(provider, "description", "No description"),
                    supported_types or "Unknown",
                    safe_get_field(provider, "status", "Unknown")
                ])
            
            click.echo(format_table(headers, rows))
            
        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to list providers: {e}")
            raise click.Abort()
    
    run_async(_list_providers())