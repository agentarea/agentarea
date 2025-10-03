"""System commands for AgentArea CLI."""

import json
from typing import TYPE_CHECKING

import click

from agentarea_cli.client import run_async
from agentarea_cli.exceptions import APIError as AgentAreaAPIError
from agentarea_cli.utils import format_table, safe_get_field

if TYPE_CHECKING:
    from agentarea_cli.client import AgentAreaClient


@click.group()
def system():
    """System management and monitoring."""
    pass


@system.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["text", "json"]),
    default="text",
    help="Output format",
)
@click.option("--detailed", is_flag=True, help="Show detailed system information")
@click.pass_context
def status(ctx, output_format: str, detailed: bool):
    """Check system status and health."""

    async def _check_status():
        client: AgentAreaClient = ctx.obj["client"]

        try:
            # Get basic health check
            health_result = await client.get("/api/v1/health")

            if output_format == "json":
                result = {"health": health_result}

                if detailed:
                    # Get additional system info
                    try:
                        stats_result = await client.get("/api/v1/system/stats")
                        result["stats"] = stats_result
                    except AgentAreaAPIError:
                        result["stats"] = {"error": "Stats not available"}

                click.echo(json.dumps(result, indent=2))
                return

            # Text format
            status_emoji = "✅" if health_result.get("status") == "healthy" else "❌"
            click.echo(f"{status_emoji} AgentArea System Status")
            click.echo(f"   Status: {health_result.get('status', 'Unknown')}")
            click.echo(f"   Version: {health_result.get('version', 'Unknown')}")
            click.echo(f"   Uptime: {health_result.get('uptime', 'Unknown')}")

            if health_result.get("timestamp"):
                click.echo(f"   Last Check: {health_result['timestamp']}")

            # Show detailed info if requested
            if detailed:
                click.echo()
                click.echo("📊 System Statistics:")

                try:
                    stats_result = await client.get("/api/v1/system/stats")

                    # Display stats
                    if "agents" in stats_result:
                        agents_stats = stats_result["agents"]
                        click.echo("   Agents:")
                        click.echo(f"     Total: {agents_stats.get('total', 0)}")
                        click.echo(f"     Active: {agents_stats.get('active', 0)}")
                        click.echo(f"     Inactive: {agents_stats.get('inactive', 0)}")

                    if "models" in stats_result:
                        models_stats = stats_result["models"]
                        click.echo("   Models:")
                        click.echo(f"     Total: {models_stats.get('total', 0)}")
                        click.echo(f"     Available: {models_stats.get('available', 0)}")
                        click.echo(f"     Providers: {models_stats.get('providers', 0)}")

                    if "chat" in stats_result:
                        chat_stats = stats_result["chat"]
                        click.echo("   Chat:")
                        click.echo(f"     Active Sessions: {chat_stats.get('active_sessions', 0)}")
                        click.echo(f"     Total Messages: {chat_stats.get('total_messages', 0)}")

                    if "system" in stats_result:
                        system_stats = stats_result["system"]
                        click.echo("   System:")
                        click.echo(f"     CPU Usage: {system_stats.get('cpu_usage', 'Unknown')}%")
                        click.echo(
                            f"     Memory Usage: {system_stats.get('memory_usage', 'Unknown')}%"
                        )
                        click.echo(f"     Disk Usage: {system_stats.get('disk_usage', 'Unknown')}%")

                except AgentAreaAPIError as e:
                    click.echo(f"   ⚠️  Stats unavailable: {e}")

        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to check system status: {e}")
            raise click.Abort()

    run_async(_check_status())


@system.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def info(ctx, output_format: str):
    """Show system information."""

    async def _get_info():
        client: AgentAreaClient = ctx.obj["client"]

        try:
            result = await client.get("/api/v1/system/info")

            if output_format == "json":
                click.echo(json.dumps(result, indent=2))
                return

            # Text format
            click.echo("ℹ️  System Information:")
            click.echo()

            # Basic info
            if "application" in result:
                app_info = result["application"]
                click.echo("Application:")
                click.echo(f"   Name: {safe_get_field(app_info, 'name', 'Unknown')}")
                click.echo(f"   Version: {safe_get_field(app_info, 'version', 'Unknown')}")
                click.echo(f"   Environment: {safe_get_field(app_info, 'environment', 'Unknown')}")
                click.echo(f"   Build: {safe_get_field(app_info, 'build', 'Unknown')}")
                click.echo()

            # Runtime info
            if "runtime" in result:
                runtime_info = result["runtime"]
                click.echo("Runtime:")
                click.echo(
                    f"   Python Version: {safe_get_field(runtime_info, 'python_version', 'Unknown')}"
                )
                click.echo(f"   Platform: {safe_get_field(runtime_info, 'platform', 'Unknown')}")
                click.echo(
                    f"   Architecture: {safe_get_field(runtime_info, 'architecture', 'Unknown')}"
                )
                click.echo()

            # Database info
            if "database" in result:
                db_info = result["database"]
                click.echo("Database:")
                click.echo(f"   Type: {safe_get_field(db_info, 'type', 'Unknown')}")
                click.echo(f"   Version: {safe_get_field(db_info, 'version', 'Unknown')}")
                click.echo(f"   Status: {safe_get_field(db_info, 'status', 'Unknown')}")
                click.echo()

            # Configuration
            if "configuration" in result:
                config_info = result["configuration"]
                click.echo("Configuration:")
                for key, value in config_info.items():
                    # Hide sensitive values
                    if any(
                        sensitive in key.lower()
                        for sensitive in ["key", "secret", "password", "token"]
                    ):
                        value = "***hidden***"
                    click.echo(f"   {key}: {value}")

        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to get system info: {e}")
            raise click.Abort()

    run_async(_get_info())


@system.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.option("--limit", default=100, help="Maximum number of logs to retrieve")
@click.option("--level", help="Filter by log level (DEBUG, INFO, WARNING, ERROR, CRITICAL)")
@click.option("--component", help="Filter by component name")
@click.pass_context
def logs(ctx, output_format: str, limit: int, level: str, component: str):
    """View system logs."""

    async def _get_logs():
        client: AgentAreaClient = ctx.obj["client"]

        params = {"limit": limit}
        if level:
            params["level"] = level.upper()
        if component:
            params["component"] = component

        try:
            result = await client.get("/api/v1/system/logs", params=params)

            logs_list = result.get("logs", [])
            if not logs_list:
                click.echo("📭 No logs found")
                return

            if output_format == "json":
                click.echo(json.dumps(logs_list, indent=2))
                return

            # Table format
            click.echo(f"📋 System Logs ({len(logs_list)} entries):")
            click.echo()

            headers = ["Timestamp", "Level", "Component", "Message"]
            rows = []

            for log_entry in logs_list:
                # Truncate long messages
                message = safe_get_field(log_entry, "message", "No message")
                if len(message) > 60:
                    message = message[:57] + "..."

                rows.append(
                    [
                        safe_get_field(log_entry, "timestamp", "Unknown")[:19],
                        safe_get_field(log_entry, "level", "Unknown"),
                        safe_get_field(log_entry, "component", "Unknown"),
                        message,
                    ]
                )

            click.echo(format_table(headers, rows))

        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to get logs: {e}")
            raise click.Abort()

    run_async(_get_logs())


@system.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def metrics(ctx, output_format: str):
    """Show system metrics."""

    async def _get_metrics():
        client: AgentAreaClient = ctx.obj["client"]

        try:
            result = await client.get("/api/v1/system/metrics")

            if output_format == "json":
                click.echo(json.dumps(result, indent=2))
                return

            # Text format
            click.echo("📈 System Metrics:")
            click.echo()

            # Performance metrics
            if "performance" in result:
                perf = result["performance"]
                click.echo("Performance:")
                click.echo(
                    f"   Average Response Time: {perf.get('avg_response_time', 'Unknown')}ms"
                )
                click.echo(f"   Requests per Second: {perf.get('requests_per_second', 'Unknown')}")
                click.echo(f"   Error Rate: {perf.get('error_rate', 'Unknown')}%")
                click.echo()

            # Resource usage
            if "resources" in result:
                resources = result["resources"]
                click.echo("Resource Usage:")
                click.echo(f"   CPU: {resources.get('cpu_percent', 'Unknown')}%")
                click.echo(f"   Memory: {resources.get('memory_percent', 'Unknown')}%")
                click.echo(f"   Disk: {resources.get('disk_percent', 'Unknown')}%")
                click.echo(f"   Network In: {resources.get('network_in', 'Unknown')} MB/s")
                click.echo(f"   Network Out: {resources.get('network_out', 'Unknown')} MB/s")
                click.echo()

            # API metrics
            if "api" in result:
                api = result["api"]
                click.echo("API Metrics:")
                click.echo(f"   Total Requests: {api.get('total_requests', 'Unknown')}")
                click.echo(f"   Successful Requests: {api.get('successful_requests', 'Unknown')}")
                click.echo(f"   Failed Requests: {api.get('failed_requests', 'Unknown')}")
                click.echo(f"   Active Connections: {api.get('active_connections', 'Unknown')}")
                click.echo()

            # Database metrics
            if "database" in result:
                db = result["database"]
                click.echo("Database Metrics:")
                click.echo(f"   Active Connections: {db.get('active_connections', 'Unknown')}")
                click.echo(f"   Query Time (avg): {db.get('avg_query_time', 'Unknown')}ms")
                click.echo(f"   Slow Queries: {db.get('slow_queries', 'Unknown')}")

        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to get metrics: {e}")
            raise click.Abort()

    run_async(_get_metrics())


@system.command()
@click.option("--component", help="Component to restart (if not provided, restarts entire system)")
@click.option("--force", is_flag=True, help="Skip confirmation prompt")
@click.pass_context
def restart(ctx, component: str, force: bool):
    """Restart system or specific component."""
    if not force:
        if component:
            message = f"Are you sure you want to restart component '{component}'?"
        else:
            message = "Are you sure you want to restart the entire system?"

        if not click.confirm(message):
            click.echo("❌ Operation cancelled")
            return

    async def _restart_system():
        client: AgentAreaClient = ctx.obj["client"]

        try:
            payload = {}
            if component:
                payload["component"] = component

            await client.post("/api/v1/system/restart", payload)

            if component:
                click.echo(f"✅ Component '{component}' restart initiated")
            else:
                click.echo("✅ System restart initiated")

            click.echo("⏳ Please wait for the system to come back online...")

        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to restart: {e}")
            raise click.Abort()

    run_async(_restart_system())


@system.command()
@click.option(
    "--format",
    "output_format",
    type=click.Choice(["table", "json"]),
    default="table",
    help="Output format",
)
@click.pass_context
def components(ctx, output_format: str):
    """List system components and their status."""

    async def _list_components():
        client: AgentAreaClient = ctx.obj["client"]

        try:
            result = await client.get("/api/v1/system/components")

            components_list = result.get("components", [])
            if not components_list:
                click.echo("📭 No components found")
                return

            if output_format == "json":
                click.echo(json.dumps(components_list, indent=2))
                return

            # Table format
            click.echo("🔧 System Components:")
            click.echo()

            headers = ["Name", "Status", "Version", "Uptime", "Health"]
            rows = []

            for component in components_list:
                status_emoji = "✅" if component.get("status") == "running" else "❌"
                health_emoji = "💚" if component.get("health") == "healthy" else "💔"

                rows.append(
                    [
                        safe_get_field(component, "name", "Unknown"),
                        f"{status_emoji} {safe_get_field(component, 'status', 'Unknown')}",
                        safe_get_field(component, "version", "Unknown"),
                        safe_get_field(component, "uptime", "Unknown"),
                        f"{health_emoji} {safe_get_field(component, 'health', 'Unknown')}",
                    ]
                )

            click.echo(format_table(headers, rows))

        except AgentAreaAPIError as e:
            click.echo(f"❌ Failed to list components: {e}")
            raise click.Abort()

    run_async(_list_components())
