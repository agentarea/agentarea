"""API CLI commands for AgentArea API."""

import asyncio
import json
import logging
import os
import sys

import click
import uvicorn
from agentarea_common.config import Database, get_db_settings
from alembic import command
from alembic.config import Config
from sqlalchemy import text

logger = logging.getLogger(__name__)


def get_engine():
    """Get database engine for migrations."""
    db = Database(get_db_settings())
    return db.sync_engine


@click.group()
def cli():
    """AgentArea API CLI - API server and database management."""
    pass


@cli.command()
@click.option(
    "--host",
    default="0.0.0.0",  # noqa: S104
    envvar="HOST",
    show_envvar=True,
    help="Host to bind the server to",
)
@click.option(
    "--port", default=8000, envvar="PORT", show_envvar=True, help="Port to bind the server to"
)
@click.option("--reload/--no-reload", default=False, help="Enable/disable auto-reload")
@click.option("--log-level", default="info", help="Logging level")
@click.option("--workers", default=1, help="Number of worker processes")
def serve(host: str, port: int, reload: bool, log_level: str, workers: int):
    """Start the API server."""
    click.echo(f"Starting AgentArea API server on {host}:{port}")
    click.echo(f"Reload: {reload}, Log Level: {log_level}, Workers: {workers}")

    uvicorn.run(
        app="agentarea_api.main:app",
        host=host,
        port=port,
        reload=reload,
        workers=workers if not reload else 1,  # Workers > 1 incompatible with reload
        log_level=log_level,
        timeout_graceful_shutdown=3 if reload else None,  # Don't hang on reload
    )


@cli.command()
def migrate():
    """Run database migrations."""
    click.echo("Running database migrations...")

    try:
        # Check database connection
        engine = get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        click.echo("Database connection successful")

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
                        "No Alembic revision found but tables exist. Stamping head without applying migrations."
                    )
                    command.stamp(alembic_cfg, head_rev or "head")
                    click.echo("Stamped database to head revision")
                else:
                    click.echo("Empty or dirty database detected. Applying migrations to head...")
                    command.upgrade(alembic_cfg, "head")
                    click.echo("Migrations applied to head")
            else:
                # Normal path: apply outstanding migrations
                command.upgrade(alembic_cfg, "head")
                click.echo("Migrations completed successfully")

    except Exception as e:
        click.echo(f"Migration failed: {e}")
        sys.exit(1)


@cli.command()
def check_migrations():
    """Check migration status."""
    click.echo("Checking migration status...")

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

            click.echo(f"Current revision: {current}")
            click.echo(f"Head revision: {head}")

            if current == head:
                click.echo("Database is up to date")
            else:
                click.echo("Database needs migration")
                sys.exit(1)

    except Exception as e:
        click.echo(f"Failed to check migrations: {e}")
        sys.exit(1)


@cli.command()
def status():
    """Check API status and configuration."""
    click.echo("API Configuration:")

    settings = get_db_settings()
    click.echo(f"Database: {settings.POSTGRES_HOST}:{settings.POSTGRES_PORT}")
    click.echo(f"Database Name: {settings.POSTGRES_DB}")
    click.echo("Port: set via --port flag or PORT env var (default: 8000)")


@cli.command()
def validate():
    """Validate API configuration and dependencies."""
    click.echo("Validating API configuration...")

    try:
        # Test database connection
        engine = get_engine()
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
        click.echo("Database connection successful")

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
                click.echo("Database migrations up to date")
            else:
                click.echo("Database needs migration")

        click.echo("API validation passed")

    except Exception as e:
        click.echo(f"Validation failed: {e}")
        sys.exit(1)


@cli.command()
@click.option(
    "--registries-config",
    envvar="REGISTRIES_CONFIG",
    default=None,
    help="JSON array of registry definitions (or REGISTRIES_CONFIG env var)",
)
@click.option(
    "--source",
    multiple=True,
    help="Registry source file/URL (can be repeated). Auto-detects type.",
)
def reconcile(registries_config: str | None, source: tuple[str, ...]):
    """Idempotent reconcile — ensure registries exist and sync them."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    asyncio.run(_reconcile(registries_config, source))


async def _reconcile(registries_config: str | None, sources: tuple[str, ...]):
    """Async reconcile implementation."""
    from agentarea_common.auth.context import UserContext
    from agentarea_mcp.infrastructure.repository import MCPServerRepository
    from agentarea_registry.application.service import RegistryService
    from agentarea_registry.infrastructure.repository import (
        RegistryItemRepository,
        RegistryRepository,
    )

    db = Database(get_db_settings())
    from agentarea_common.constants import PLATFORM_PRINCIPAL_ID, PLATFORM_WORKSPACE_ID

    system_context = UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=PLATFORM_WORKSPACE_ID)

    # Build registry configs from args
    configs: list[dict] = []

    if registries_config:
        try:
            configs = json.loads(registries_config)
            click.echo(f"Loaded {len(configs)} registries from config")
        except json.JSONDecodeError as e:
            click.echo(f"Failed to parse REGISTRIES_CONFIG: {e}")
            sys.exit(1)

    # Add any --source args as auto-detected registries
    for src in sources:
        name = (
            os.path.basename(src).rsplit(".", 1)[0]
            if not src.startswith("http")
            else src.split("/")[-1]
        )
        configs.append(
            {
                "name": name,
                "type": "mcp_servers",
                "source_type": "url",
                "source_url": src,
            }
        )

    if not configs:
        click.echo("No registry config provided (set REGISTRIES_CONFIG or use --source)")
        return

    skill_repo_cls = None
    try:
        from agentarea_agents.infrastructure.skill_repository import SkillRepository

        skill_repo_cls = SkillRepository
    except ImportError:
        pass

    provider_spec_repo_cls = None
    model_spec_repo_cls = None
    try:
        from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
        from agentarea_llm.infrastructure.provider_spec_repository import ProviderSpecRepository

        provider_spec_repo_cls = ProviderSpecRepository
        model_spec_repo_cls = ModelSpecRepository
    except ImportError:
        pass

    agent_repo_cls = None
    try:
        from agentarea_agents.infrastructure.repository import AgentRepository

        agent_repo_cls = AgentRepository
    except ImportError:
        pass

    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []

    for config in configs:
        registry_name = config["name"]
        click.echo(f"\nReconciling: {registry_name}")

        try:
            async with db.async_session_factory() as session:
                registry_repo = RegistryRepository(session, system_context)
                item_repo = RegistryItemRepository(session, system_context)
                server_repo = MCPServerRepository(session, system_context)
                skill_repo = skill_repo_cls(session, system_context) if skill_repo_cls else None
                provider_spec_repo = (
                    provider_spec_repo_cls(session, system_context)
                    if provider_spec_repo_cls
                    else None
                )
                model_spec_repo = (
                    model_spec_repo_cls(session, system_context) if model_spec_repo_cls else None
                )
                agent_repo = agent_repo_cls(session, system_context) if agent_repo_cls else None
                service = RegistryService(
                    registry_repo,
                    item_repo,
                    server_repo,
                    skill_repo=skill_repo,
                    provider_spec_repo=provider_spec_repo,
                    model_spec_repo=model_spec_repo,
                    agent_repo=agent_repo,
                )

                registries = await registry_repo.list_all()
                existing = next((r for r in registries if r.name == registry_name), None)
                if existing:
                    registry_id = existing.id
                    click.echo(f"Found existing registry: {registry_id}")
                else:
                    registry = await service.create_registry(
                        name=registry_name,
                        registry_type=config.get("type", "mcp_servers"),
                        source_type=config.get("source_type", "url"),
                        source_url=config["source_url"],
                        description=config.get("description"),
                        sync_mode=config.get("sync_mode", "manual"),
                    )
                    registry_id = registry.id
                    click.echo(f"Created registry: {registry_id}")

                stats = await service.sync_registry(registry_id)
                await session.commit()
                click.echo(f"Synced: {stats}")
                succeeded.append(registry_name)
        except Exception as e:
            logger.exception("Reconcile failed for registry %s", registry_name)
            click.echo(f"Reconcile failed for {registry_name}: {e}", err=True)
            failed.append((registry_name, str(e)))

    click.echo(
        f"\nReconcile complete: {len(succeeded)} succeeded, {len(failed)} failed "
        f"(out of {len(configs)})"
    )
    if failed:
        for name, err in failed:
            click.echo(f"  - {name}: {err}", err=True)
        sys.exit(1)


if __name__ == "__main__":
    cli()
