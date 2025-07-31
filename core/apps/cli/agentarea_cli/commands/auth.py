"""Authentication commands for AgentArea CLI."""

from typing import TYPE_CHECKING

import click

from agentarea_common.auth import UserContext
from agentarea_cli.client import run_async
from agentarea_cli.exceptions import AgentAreaAPIError, AuthenticationError

if TYPE_CHECKING:
    from agentarea_cli.client import AgentAreaClient
    from agentarea_cli.config import AuthConfig


@click.group()
def auth():
    """Authentication commands."""
    pass


@auth.command()
@click.option("--user-id", default="test-user", help="User ID for test authentication")
@click.option("--admin", is_flag=True, help="Generate admin token")
@click.pass_context
def login(ctx, user_id: str, admin: bool):
    """Login to AgentArea (generates test JWT token)."""
    
    async def _login():
        try:
            # Import here to avoid import errors if agentarea_common is not available
            if admin:
                from agentarea_common.auth.test_utils import create_admin_test_token
                token = create_admin_test_token(user_id=user_id)
                role = "Admin"
            else:
                from agentarea_common.auth.test_utils import create_basic_test_token
                token = create_basic_test_token(user_id=user_id)
                role = "User"
            
            # Store token
            auth_config: "AuthConfig" = ctx.obj["auth_config"]
            auth_config.set_token(token)
            
            click.echo(f"✅ Successfully logged in as {user_id}")
            click.echo(f"   Role: {role}")
            
            # Test the token by calling /auth/users/me
            client: "AgentAreaClient" = ctx.obj["client"]
            try:
                result = await client.get("/api/v1/auth/users/me")
                click.echo(f"   Token verified: {result.get('user_id', 'Unknown')}")
            except AgentAreaAPIError as e:
                click.echo(f"   Warning: Could not verify token: {e}")
                
        except ImportError as e:
            click.echo(f"❌ Login failed: Missing authentication utilities - {e}")
            click.echo("   Make sure agentarea_common is properly installed")
            raise click.Abort()
        except Exception as e:
            click.echo(f"❌ Login failed: {e}")
            raise click.Abort()
    
    run_async(_login())


@auth.command()
@click.pass_context
def logout(ctx):
    """Logout from AgentArea."""
    auth_config: "AuthConfig" = ctx.obj["auth_config"]
    
    if not auth_config.is_authenticated():
        click.echo("❌ Not currently logged in")
        return
    
    auth_config.clear_auth()
    click.echo("✅ Successfully logged out")


@auth.command()
@click.pass_context
def status(ctx):
    """Check authentication status."""
    
    async def _status():
        auth_config: "AuthConfig" = ctx.obj["auth_config"]
        
        if not auth_config.is_authenticated():
            click.echo("❌ Not authenticated")
            click.echo("   Run 'agentarea auth login' to authenticate")
            return
        
        click.echo("✅ Authenticated")
        click.echo(f"   API URL: {auth_config.get_api_url()}")
        
        # Try to get user info
        client: "AgentAreaClient" = ctx.obj["client"]
        try:
            result = await client.get("/api/v1/auth/users/me")
            click.echo(f"   User ID: {result.get('user_id', 'Unknown')}")
            
            # Handle both single role and multiple roles
            roles = result.get('roles', [])
            if isinstance(roles, str):
                roles = [roles]
            elif not isinstance(roles, list):
                roles = []
            
            if roles:
                click.echo(f"   Roles: {', '.join(roles)}")
            else:
                click.echo("   Roles: None")
                
        except AuthenticationError:
            click.echo("   ❌ Token is invalid or expired")
            click.echo("   Run 'agentarea auth login' to re-authenticate")
        except AgentAreaAPIError as e:
            click.echo(f"   Warning: Could not fetch user info: {e}")
    
    run_async(_status())


@auth.command()
@click.option("--api-url", help="Set the API URL")
@click.pass_context
def config(ctx, api_url: str):
    """Configure authentication settings."""
    auth_config: "AuthConfig" = ctx.obj["auth_config"]
    
    if api_url:
        auth_config.set_api_url(api_url)
        click.echo(f"✅ API URL set to: {api_url}")
    else:
        # Show current configuration
        click.echo("Current configuration:")
        click.echo(f"   API URL: {auth_config.get_api_url()}")
        click.echo(f"   Authenticated: {'Yes' if auth_config.is_authenticated() else 'No'}")