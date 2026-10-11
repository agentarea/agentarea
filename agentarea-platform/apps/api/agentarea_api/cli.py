"""API CLI commands for AgentArea API."""

import asyncio
import json
import logging
import os
import sys
from pathlib import Path

import click
import uvicorn
from agentarea_common.config import Database, get_db_settings
from agentarea_common.rebac.openfga_client import OpenFGAClient
from alembic import command
from alembic.config import Config
from sqlalchemy import text

logger = logging.getLogger(__name__)


def get_engine():
    """Get database engine for migrations."""
    db = Database(get_db_settings())
    return db.sync_engine


def reload_dirs(cli_file: Path) -> list[str]:
    """The directories ``serve --reload`` watches: the API package and the workspace libs.

    *cli_file* sits at ``<root>/apps/api/agentarea_api/cli.py``, the libs at
    ``<root>/libs``, both in a checkout and in the image.
    """
    package_dir = cli_file.resolve().parent
    libs_dir = package_dir.parents[2] / "libs"
    if not libs_dir.is_dir():
        raise click.UsageError(
            f"--reload watches the workspace libs, but {libs_dir} does not exist"
        )
    return [str(package_dir), str(libs_dir)]


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
@click.option(
    "--log-level",
    default="info",
    envvar="AGENTAREA_LOG_LEVEL",
    show_envvar=True,
    help="Logging level",
)
@click.option(
    "--workers",
    default=1,
    envvar="AGENTAREA_API_WORKERS",
    show_envvar=True,
    help=(
        "Worker processes. One process is one event loop, so roughly one CPU "
        "core however many the pod is allowed; raise this only to match a "
        "larger CPU limit, otherwise add replicas."
    ),
)
@click.option(
    "--shutdown-timeout",
    default=20,
    envvar="AGENTAREA_API_SHUTDOWN_TIMEOUT",
    show_envvar=True,
    help=(
        "Seconds to wait on SIGTERM for open connections to finish. Must stay "
        "below the pod's terminationGracePeriodSeconds, minus any preStop wait."
    ),
)
def serve(host: str, port: int, reload: bool, log_level: str, workers: int, shutdown_timeout: int):
    """Start the API server."""
    from agentarea_common.config import MetricsSettings

    metrics = MetricsSettings()
    if metrics.ENABLED and workers > 1 and not reload:
        # Each worker process would bind AGENTAREA_METRICS_PORT; the second one fails,
        # and the first would only ever report its own share of requests.
        raise click.UsageError(
            "AGENTAREA_METRICS_ENABLED needs a single worker process per pod; "
            "scale with replicas instead of AGENTAREA_API_WORKERS"
        )

    click.echo(f"Starting AgentArea API server on {host}:{port}")
    click.echo(f"Reload: {reload}, Log Level: {log_level}, Workers: {workers}")

    uvicorn.run(
        app="agentarea_api.main:app",
        host=host,
        port=port,
        reload=reload,
        reload_dirs=reload_dirs(Path(__file__)) if reload else None,
        workers=workers if not reload else 1,  # Workers > 1 incompatible with reload
        log_level=log_level,
        # Bounded, always. The API serves SSE, and those connections never end
        # on their own: waiting for every connection to close meant the process
        # sat until the pod's grace period expired and was killed, dropping
        # whatever else was still in flight on each rollout.
        timeout_graceful_shutdown=3 if reload else shutdown_timeout,
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
    click.echo(f"Database: {settings.HOST}:{settings.PORT}")
    click.echo(f"Database Name: {settings.NAME}")
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
    help="Registry source file/URL (can be repeated). Type is auto-detected.",
)
@click.option(
    "--config-file",
    default=None,
    help="Path to a YAML/JSON manifest listing registry sources.",
)
@click.option(
    "--wait-for-schema",
    default=None,
    help="Wait up to this long (e.g. 300s) for the database to reach the migration head.",
)
@click.option(
    "--repair-ownership",
    is_flag=True,
    default=False,
    help="First grant ownership to governed rows a migration inserted by SQL. For the "
    "post-migration run only: it reads the whole authorization graph.",
)
def reconcile(
    registries_config: str | None,
    source: tuple[str, ...],
    config_file: str | None,
    wait_for_schema: str | None,
    repair_ownership: bool,
):
    """Idempotent catalog reconcile; with --repair-ownership, graph ownership first."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    if wait_for_schema is not None:
        from agentarea_common.config.duration import parse_duration

        _wait_for_schema_head(parse_duration(wait_for_schema).total_seconds())
    asyncio.run(_reconcile(registries_config, source, config_file, repair_ownership))


def _wait_for_schema_head(timeout_seconds: float, poll_seconds: float = 5.0) -> None:
    """Block until the database is at the migration head.

    The chart starts this Job alongside the migration Job. Rows a data migration
    writes by SQL get no graph tuples, so the ownership pass has to run after the
    migration commits or it walks the tables before those rows exist.
    """
    import time

    from alembic.runtime.migration import MigrationContext
    from alembic.script import ScriptDirectory

    head = ScriptDirectory.from_config(Config("alembic.ini")).get_current_head()
    deadline = time.monotonic() + timeout_seconds
    engine = get_engine()
    while True:
        with engine.connect() as connection:
            current = MigrationContext.configure(connection).get_current_revision()
        if current == head:
            click.echo(f"Database at migration head {head}")
            return
        if time.monotonic() >= deadline:
            raise click.ClickException(
                f"database is at revision {current}, not the head {head}, "
                f"after waiting {timeout_seconds:.0f}s for the migration Job"
            )
        click.echo(f"Waiting for migrations: at {current}, head is {head}")
        time.sleep(poll_seconds)


async def _register_graph_client() -> OpenFGAClient:
    """Register the authorization-graph client the API and worker register.

    Materializing a catalog skill creates a Skill row, and
    ``WorkspaceScopedRepository.create`` records its owner in the graph. Without
    a registered client every new skill failed with "no client is registered"
    and was skipped. The model is the API's to apply; here only the store is
    resolved.
    """
    # The graph settings alone: the full application Settings also demands
    # Temporal configuration, which a reconcile pod has no use for.
    from agentarea_common.config.access_control import AccessControlSettings
    from agentarea_common.config.openfga import OpenFGASettings
    from agentarea_common.di.container import register_singleton
    from agentarea_common.rebac.openfga_bootstrap import bootstrap_openfga

    backend = AccessControlSettings().BACKEND
    openfga = OpenFGASettings()
    await bootstrap_openfga(openfga)
    client = OpenFGAClient(
        api_url=openfga.URL,
        store_id=openfga.STORE_ID,
        authorization_model_id=openfga.MODEL_ID,
        timeout_seconds=openfga.TIMEOUT.total_seconds(),
        api_token=openfga.API_TOKEN or None,
    )
    register_singleton(OpenFGAClient, client)
    click.echo(f"Authorization graph: {backend}")
    return client


async def _reconcile_graph_ownership(db: Database, client: OpenFGAClient) -> None:
    """Grant governed rows a migration inserted by SQL the ownership tuples they lack."""
    from agentarea_common.rebac.ownership_reconcile import reconcile_graph_ownership

    async with db.async_session_factory() as session:
        result = await reconcile_graph_ownership(session, client)
    click.echo(
        f"Graph ownership: wrote {result.written} tuples across {result.resources} resources, "
        f"{result.workspaces} workspaces and {result.memberships} memberships"
    )


async def _reconcile(
    registries_config: str | None,
    sources: tuple[str, ...],
    config_file: str | None = None,
    repair_ownership: bool = False,
):
    """Async reconcile implementation."""
    from agentarea_common.auth.context import UserContext
    from agentarea_common.base.tenant_scope import workspace_scope
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

    # Load a manifest file (YAML or JSON list of registry definitions)
    if config_file:
        import yaml

        try:
            with open(config_file) as f:
                file_configs = yaml.safe_load(f)
        except (OSError, yaml.YAMLError) as e:
            click.echo(f"Failed to read --config-file {config_file}: {e}")
            sys.exit(1)
        if not isinstance(file_configs, list):
            click.echo(f"--config-file {config_file} must contain a list of registries")
            sys.exit(1)
        configs.extend(file_configs)
        click.echo(f"Loaded {len(file_configs)} registries from {config_file}")

    # Add any --source args (type is inferred from the fetched payload)
    for src in sources:
        name = (
            os.path.basename(src).rsplit(".", 1)[0]
            if not src.startswith("http")
            else src.split("/")[-1]
        )
        configs.append({"name": name, "source_url": src})

    # Ownership of governed rows is granted by the repository when a row is
    # created. Only rows a migration inserts by SQL need repair, so only the
    # post-migration run asks for it: the hourly catalog run read the whole
    # graph into memory each time and was OOM-killed.
    client = await _register_graph_client()
    if repair_ownership:
        await _reconcile_graph_ownership(db, client)

    if not configs:
        click.echo("No registry config provided (set REGISTRIES_CONFIG or use --source)")
        return

    # Validate up front so a malformed entry reports a clear message instead of
    # failing deep inside the per-registry loop with a bare KeyError.
    for i, config in enumerate(configs):
        retired = isinstance(config, dict) and config.get("active", True) is False
        if (
            not isinstance(config, dict)
            or "name" not in config
            or ("source_url" not in config and not retired)
        ):
            click.echo(f"Registry entry {i} must be a mapping with 'name' and 'source_url'")
            sys.exit(1)

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
            with workspace_scope(PLATFORM_WORKSPACE_ID):
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
                        model_spec_repo_cls(session, system_context)
                        if model_spec_repo_cls
                        else None
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
                    if config.get("active", True) is False:
                        # A source dropped from the manifest is never reconciled
                        # again, so its registry and items would stay listed.
                        if existing is not None and existing.is_active:
                            await service.update_registry(existing.id, is_active=False)
                            click.echo(f"Retired registry: {existing.id}")
                        else:
                            click.echo("Registry already retired or absent")
                        succeeded.append(registry_name)
                        continue
                    configured_priority = config.get("recommendation_priority")
                    if existing:
                        registry_id = existing.id
                        click.echo(f"Found existing registry: {registry_id}")
                        # Reconcile is the only way a manifest edit reaches an
                        # installed platform: without this, changing a source's
                        # weight would only ever affect brand-new installs.
                        if (
                            configured_priority is not None
                            and configured_priority != existing.recommendation_priority
                        ):
                            await service.update_registry(
                                registry_id, recommendation_priority=configured_priority
                            )
                            click.echo(f"Updated recommendation priority: {configured_priority}")
                    else:
                        registry_type = config.get("type")
                        if not registry_type:
                            # Detection fetches the source to inspect its shape; the
                            # subsequent sync_registry fetches it again to parse. The
                            # extra GET is acceptable for a one-shot reconcile — set an
                            # explicit `type` in the manifest to skip detection.
                            registry_type = service.detect_type_from_source(config["source_url"])
                            click.echo(f"Detected type: {registry_type}")
                        registry = await service.create_registry(
                            name=registry_name,
                            registry_type=registry_type,
                            source_type=config.get("source_type", "url"),
                            source_url=config["source_url"],
                            description=config.get("description"),
                            sync_mode=config.get("sync_mode", "manual"),
                            recommendation_priority=configured_priority,
                        )
                        registry_id = registry.id
                        click.echo(f"Created registry: {registry_id}")

                    stats = await service.sync_registry(registry_id)
                    await session.commit()
                    click.echo(f"Synced: {stats}")
                    if stats.get("skipped"):
                        click.echo(
                            f"  WARNING: skipped {stats['skipped']} item(s) "
                            "that failed validation (see logs for reasons)",
                            err=True,
                        )
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
