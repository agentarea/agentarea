"""API CLI commands for AgentArea API."""

import os
import sys

import click
import uvicorn
from agentarea_common.config import Database, get_db_settings
from alembic import command
from alembic.config import Config
from sqlalchemy import text


def get_engine():
    """Get database engine for migrations."""
    db = Database(get_db_settings())
    return db.sync_engine


@click.group()
def cli():
    """AgentArea API CLI - API server and database management."""
    pass


@cli.command()
@click.option("--host", default="0.0.0.0", help="Host to bind the server to")  # noqa: S104
@click.option("--port", default=8000, help="Port to bind the server to")
@click.option("--reload/--no-reload", default=False, help="Enable/disable auto-reload")
@click.option("--log-level", default="info", help="Logging level")
@click.option("--workers", default=1, help="Number of worker processes")
def serve(host: str, port: int, reload: bool, log_level: str, workers: int):
    """Start the API server."""
    click.echo(f"🚀 Starting AgentArea API server on {host}:{port}")
    click.echo(f"   Reload: {reload}, Log Level: {log_level}, Workers: {workers}")

    uvicorn.run(
        app="agentarea_api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,  # Workers > 1 incompatible with reload
        log_level=log_level,
    )


@cli.command()
def migrate():
    """Run database migrations."""
    click.echo("🔄 Running database migrations...")

    try:
        # Check database connection
        engine = get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        click.echo("✅ Database connection successful")

        # Determine current revision and handle pre-existing schema gracefully
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory
        from sqlalchemy import inspect

        alembic_cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)
        head_rev = script.get_current_head()

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current = context.get_current_revision()

            if current is None:
                inspector = inspect(connection)
                existing_tables = set(inspector.get_table_names())

                # If schema already exists (e.g., tables created by bootstrap), stamp head
                # Only stamp if provider_specs exists, otherwise it might be a dirty DB (e.g. Kratos tables)
                if existing_tables and "provider_specs" in existing_tables:
                    click.echo(
                        "⚠️  No Alembic revision found but tables exist. Stamping head without applying migrations."
                    )
                    command.stamp(alembic_cfg, head_rev)
                    click.echo("✅ Stamped database to head revision")
                else:
                    click.echo("Empty or dirty database detected. Applying migrations to head...")
                    command.upgrade(alembic_cfg, "head")
                    click.echo("✅ Migrations applied to head")
            else:
                # Normal path: apply outstanding migrations
                command.upgrade(alembic_cfg, "head")
                click.echo("✅ Migrations completed successfully")

    except Exception as e:
        click.echo(f"❌ Migration failed: {e}")
        sys.exit(1)


@cli.command()
def check_migrations():
    """Check migration status."""
    click.echo("🔍 Checking migration status...")

    try:
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        engine = get_engine()
        alembic_cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current = context.get_current_revision()
            head = script.get_current_head()

            click.echo(f"   Current revision: {current}")
            click.echo(f"   Head revision: {head}")

            if current == head:
                click.echo("✅ Database is up to date")
            else:
                click.echo("⚠️  Database needs migration")
                sys.exit(1)

    except Exception as e:
        click.echo(f"❌ Failed to check migrations: {e}")
        sys.exit(1)


@cli.command()
def status():
    """Check API status and configuration."""
    click.echo("🔍 API Configuration:")

    settings = get_db_settings()
    click.echo(f"   Database: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}")
    click.echo(f"   Database Name: {settings.POSTGRES_DB}")
    click.echo(f"   Port: {os.getenv('PORT', '8000')}")


@cli.command()
def validate():
    """Validate API configuration and dependencies."""
    click.echo("🔍 Validating API configuration...")

    try:
        # Test database connection
        engine = get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        click.echo("✅ Database connection successful")

        # Check if migrations are up to date
        from alembic.runtime.migration import MigrationContext
        from alembic.script import ScriptDirectory

        alembic_cfg = Config("alembic.ini")
        script = ScriptDirectory.from_config(alembic_cfg)

        with engine.connect() as connection:
            context = MigrationContext.configure(connection)
            current = context.get_current_revision()
            head = script.get_current_head()

            if current == head:
                click.echo("✅ Database migrations up to date")
            else:
                click.echo("⚠️  Database needs migration")

        click.echo("✅ API validation passed")

    except Exception as e:
        click.echo(f"❌ Validation failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    cli()
