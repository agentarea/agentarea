"""Worker CLI commands for AgentArea Worker."""

import asyncio
import logging
import sys
from typing import Optional

import click
from agentarea_common.config import get_settings
from agentarea_worker.main import AgentAreaWorker

logger = logging.getLogger(__name__)


@click.group()
def cli():
    """AgentArea Worker CLI - Temporal worker management."""
    pass


@cli.command()
@click.option("--debug", is_flag=True, help="Enable debug logging")
@click.option("--max-activities", type=int, help="Max concurrent activities")
@click.option("--max-workflows", type=int, help="Max concurrent workflows")
def start(debug: bool, max_activities: Optional[int], max_workflows: Optional[int]):
    """Start the Temporal worker."""
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    
    settings = get_settings()
    
    # Override settings if provided
    if max_activities:
        settings.workflow.TEMPORAL_MAX_CONCURRENT_ACTIVITIES = max_activities
    if max_workflows:
        settings.workflow.TEMPORAL_MAX_CONCURRENT_WORKFLOWS = max_workflows
    
    click.echo("🚀 Starting AgentArea Temporal Worker...")
    click.echo(f"   Temporal Server: {settings.workflow.TEMPORAL_SERVER_URL}")
    click.echo(f"   Task Queue: {settings.workflow.TEMPORAL_TASK_QUEUE}")
    click.echo(f"   Max Activities: {settings.workflow.TEMPORAL_MAX_CONCURRENT_ACTIVITIES}")
    click.echo(f"   Max Workflows: {settings.workflow.TEMPORAL_MAX_CONCURRENT_WORKFLOWS}")
    
    try:
        worker = AgentAreaWorker()
        asyncio.run(worker.start())
    except KeyboardInterrupt:
        click.echo("\n✅ Worker stopped by user")
    except Exception as e:
        click.echo(f"\n❌ Worker failed: {e}")
        sys.exit(1)


@cli.command()
@click.option("--debug", is_flag=True, help="Enable debug logging")
def dev(debug: bool):
    """Start the worker with auto-restart on file changes (development mode)."""
    import subprocess
    
    if debug:
        logging.basicConfig(level=logging.DEBUG)
    
    click.echo("🚀 Starting Temporal worker with auto-restart...")
    click.echo("📝 Watching for Python file changes in apps/worker and libs directories")
    click.echo("Press Ctrl+C to stop")
    
    try:
        # Run watchfiles to monitor and restart the worker
        subprocess.run([
            sys.executable, "-m", "watchfiles",
            "python -m agentarea_worker.cli start",
            "/app/apps/worker",
            "/app/libs"
        ], cwd="/app")
    except KeyboardInterrupt:
        click.echo("\n✅ Worker auto-restart stopped")
    except Exception as e:
        click.echo(f"\n❌ Error: {e}")
        sys.exit(1)


@cli.command()
def status():
    """Check worker status and configuration."""
    settings = get_settings()
    
    click.echo("🔍 Worker Configuration:")
    click.echo(f"   Temporal Server: {settings.workflow.TEMPORAL_SERVER_URL}")
    click.echo(f"   Namespace: {settings.workflow.TEMPORAL_NAMESPACE}")
    click.echo(f"   Task Queue: {settings.workflow.TEMPORAL_TASK_QUEUE}")
    click.echo(f"   Database: {settings.database.POSTGRES_HOST}:{settings.database.POSTGRES_PORT}")


@cli.command()
def validate():
    """Validate worker configuration and dependencies."""
    click.echo("🔍 Validating worker configuration...")
    
    try:
        settings = get_settings()
        click.echo("✅ Settings loaded successfully")
        
        # Test database connection
        from agentarea_common.config import Database
        from sqlalchemy import text
        db = Database(settings.database)
        with db.get_sync_db() as session:
            session.execute(text("SELECT 1"))
        click.echo("✅ Database connection successful")
        
        click.echo("✅ Worker validation passed")
        
    except Exception as e:
        click.echo(f"❌ Validation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
