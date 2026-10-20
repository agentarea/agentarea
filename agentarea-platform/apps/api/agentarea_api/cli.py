"""API CLI commands for AgentArea API."""

import asyncio
import json
import logging
import os
import sys
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any
from uuid import UUID

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
    "--force",
    is_flag=True,
    help="Re-read every source even if its ETag is the one last applied.",
)
@click.option(
    "--workspace-registries",
    is_flag=True,
    help="Also sync every active registry a workspace added (ADR-0044).",
)
def reconcile(
    registries_config: str | None,
    source: tuple[str, ...],
    config_file: str | None,
    force: bool,
    workspace_registries: bool,
):
    """Idempotent reconcile — ensure registries exist and sync them."""
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")

    asyncio.run(
        _reconcile(
            registries_config,
            source,
            config_file,
            force=force,
            workspace_registries=workspace_registries,
        )
    )


@cli.group()
def skills():
    """Skill maintenance."""


@skills.command("move-bodies-to-packages")
def move_bodies_to_packages():
    """Move every skill body still stored in its row into the skill's package (ADR-0044).

    Reading such a skill moves it too; this does all of them up front. A row
    that also has a package was edited after its import, which wrote only the
    row: the edit goes into the workspace's own copy of the package. Safe to
    run again: a row without a body is left alone. The platform workspace's
    stub copies are skipped; the reconcile deletes them.

    Run it only once every worker runs this release: an older worker reads
    the body from the row and would run a moved skill with an empty prompt.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_move_bodies_to_packages())


def _require_object_storage() -> None:
    from agentarea_common.config.aws import (
        ObjectStorageNotConfiguredError,
        require_s3_credentials,
    )

    try:
        require_s3_credentials()
    except ObjectStorageNotConfiguredError as e:
        click.echo(f"Skill packages live in object storage, and {e}", err=True)
        sys.exit(1)


async def _move_bodies_to_packages() -> None:
    from agentarea_agents.application.skill_packages import move_all_bodies_to_packages
    from agentarea_agents.infrastructure.skill_storage_service import SkillStorageService

    _require_object_storage()
    db = Database(get_db_settings())
    moved, failed = await move_all_bodies_to_packages(
        db.async_session_factory, SkillStorageService()
    )
    click.echo(f"Moved {moved} skill bodies into packages; {failed} failed")
    if failed:
        sys.exit(1)


@skills.command("repin-catalog-installs")
@click.option("--dry-run", is_flag=True, help="Report what would be repinned; change nothing.")
def repin_catalog_installs(dry_run: bool):
    """Repin catalog installs made before packages existed, if nobody edited them (ADR-0044).

    Such a skill holds the body its install copied, so it reads as edited.
    One whose body is still what its catalog item gave it is re-installed from
    the item's current package (pinned), keeping its id and agents. Edited
    skills are left alone and reported; so is a skill whose item is gone.
    Run after ``move-bodies-to-packages`` and the reconcile.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_repin_catalog_installs(dry_run=dry_run))


async def _repin_catalog_installs(*, dry_run: bool) -> None:
    from collections import Counter

    from agentarea_agents.application import skill_service
    from agentarea_agents.infrastructure.skill_storage_service import SkillStorageService

    _require_object_storage()
    db = Database(get_db_settings())
    results = await skill_service.repin_all_catalog_installs(
        db.async_session_factory, SkillStorageService(), dry_run=dry_run
    )
    for workspace_id, result in results:
        line = f"{result.status}  {workspace_id}/{result.skill_id}  {result.name}"
        click.echo(f"{line}: {result.error}" if result.error else line)
    counts = Counter(result.status for _, result in results)
    click.echo(", ".join(f"{n} {status}" for status, n in counts.items()) or "No catalog installs")
    if counts["failed"]:
        sys.exit(1)


async def _register_graph_client() -> None:
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
    register_singleton(
        OpenFGAClient,
        OpenFGAClient(
            api_url=openfga.URL,
            store_id=openfga.STORE_ID,
            authorization_model_id=openfga.MODEL_ID,
            timeout_seconds=openfga.TIMEOUT.total_seconds(),
            api_token=openfga.API_TOKEN or None,
        ),
    )
    click.echo(f"Authorization graph: {backend}")


@asynccontextmanager
async def _registry_sync_lock(db: Database, key: str) -> AsyncIterator[bool]:
    """Whether this run may sync the registry ``key`` names: one run at a time.

    The ArgoCD Sync hook and the hourly CronJob can reconcile at once. A
    session-level advisory lock on its own connection, in autocommit so the
    run holds no transaction open; the second run to reach a registry skips it.
    A session lock needs a direct connection or a session-mode pooler: behind
    a transaction-mode pooler it would outlive the run and skip forever.
    """
    async with db.engine.connect() as conn:
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT")
        held = bool(
            (
                await conn.execute(
                    text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"), {"key": key}
                )
            ).scalar_one()
        )
        try:
            yield held
        finally:
            if held:
                try:
                    await conn.execute(
                        text("SELECT pg_advisory_unlock(hashtextextended(:key, 0))"), {"key": key}
                    )
                except Exception:
                    # The connection is gone and its session's lock with it;
                    # what the sync did stands.
                    logger.exception("Could not release the reconcile lock %s", key)


# What a manifest entry leaves out of its source is the default a new registry gets.
_SOURCE_DEFAULTS: dict[str, str | None] = {
    "source_type": "url",
    "source_ref": None,
    "source_path": None,
}


def manifest_registry_type(config: dict, detect: Callable[[str], str]) -> str:
    """The registry type of a manifest entry: stated, implied by a GitHub source, or detected.

    ``detect`` fetches the source to read its shape, so it is asked only for an
    index entry that states no type.
    """
    registry_type = config.get("type")
    if config.get("source_type") == "github":
        if registry_type not in (None, "skills"):
            raise ValueError(
                f"Registry {config['name']!r}: a github source holds skills, not {registry_type!r}"
            )
        return "skills"
    return registry_type or detect(config["source_url"])


# Every field reconcile applies to an existing platform registry.
_RECONCILED_FIELDS = (
    "source_type",
    "source_url",
    "source_ref",
    "source_path",
    "mode",
    "trust",
    "recommendation_priority",
    "credentials_secret_ref",
)


async def reconcile_existing_registry(
    service: Any, existing: Any, config: dict, *, credentials_secret_ref: UUID | None
) -> list[str]:
    """Make an existing platform registry what its manifest entry says.

    Returns the names of the fields that changed, never their values: one is
    a credentials reference.

    The source fields, ``mode``, ``trust``, ``recommendation_priority`` and the
    credentials reference are applied in one update; the service clears the
    stored ETag when the source or the mode changed, so the next sync reads the
    source in full. A changed type is refused: the items of one type are not
    another's.
    """
    registry_type = config.get("type")
    if registry_type and registry_type != existing.registry_type:
        raise ValueError(
            f"Registry {existing.name!r} holds {existing.registry_type}, the manifest says "
            f"{registry_type}: retire it (active: false) and add the new source under a new name"
        )
    wanted: dict[str, Any] = {
        "source_url": config["source_url"],
        **{field: config.get(field, default) for field, default in _SOURCE_DEFAULTS.items()},
        **{field: config[field] for field in ("mode", "trust") if field in config},
        "credentials_secret_ref": credentials_secret_ref,
    }
    if config.get("recommendation_priority") is not None:
        wanted["recommendation_priority"] = config["recommendation_priority"]
    changes = {field: value for field, value in wanted.items() if value != getattr(existing, field)}
    changed = [field for field in _RECONCILED_FIELDS if field in changes]
    if changed:
        await service.update_registry(existing.id, **changes)
        logger.info(
            "Reconcile changed registry %s (%s): %s", existing.name, existing.id, ", ".join(changed)
        )
    return changed


async def _reconcile(
    registries_config: str | None,
    sources: tuple[str, ...],
    config_file: str | None = None,
    force: bool = False,
    workspace_registries: bool = False,
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

    from agentarea_api.registry_content import registry_content_mirror
    from agentarea_api.registry_credentials import (
        platform_secret_id,
        record_registry_secret_reference,
        registry_credentials_resolver,
    )

    db = Database(get_db_settings())
    content_mirror = registry_content_mirror()
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

    if not configs and not workspace_registries:
        click.echo("No registry config provided (set REGISTRIES_CONFIG or use --source)")
        return

    await _register_graph_client()

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
    skipped: list[str] = []
    # Retired entries last: an install of a retired registry's item moves to
    # the registry replacing it, which must be synced by then.
    retired = [c for c in configs if c.get("active", True) is False]
    ordered = [c for c in configs if c.get("active", True) is not False] + retired
    replacements: list = []

    for config in ordered:
        registry_name = config["name"]
        click.echo(f"\nReconciling: {registry_name}")

        try:
            async with _registry_sync_lock(db, f"registry-sync:platform:{registry_name}") as held:
                if not held:
                    click.echo(f"Skipped {registry_name}: another reconcile is syncing it")
                    skipped.append(registry_name)
                    continue
                with workspace_scope(PLATFORM_WORKSPACE_ID):
                    async with db.async_session_factory() as session:
                        registry_repo = RegistryRepository(session, system_context)
                        item_repo = RegistryItemRepository(session, system_context)
                        server_repo = MCPServerRepository(session, system_context)
                        skill_repo = (
                            skill_repo_cls(session, system_context) if skill_repo_cls else None
                        )
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
                        agent_repo = (
                            agent_repo_cls(session, system_context) if agent_repo_cls else None
                        )
                        service = RegistryService(
                            registry_repo,
                            item_repo,
                            server_repo,
                            skill_repo=skill_repo,
                            provider_spec_repo=provider_spec_repo,
                            model_spec_repo=model_spec_repo,
                            agent_repo=agent_repo,
                            credentials_resolver=registry_credentials_resolver(session),
                            content_mirror=content_mirror,
                        )

                        # The manifest names platform registries; a workspace's own
                        # registry may share the name.
                        existing = await registry_repo.get_platform_by_name(registry_name)
                        if config.get("active", True) is False:
                            # A source dropped from the manifest is never reconciled
                            # again, so its registry and items would stay listed; what
                            # nothing uses is deleted, the rest stays out of the catalog.
                            if existing is not None:
                                deleted = await service.retire_registry(
                                    existing.id, replacements=replacements
                                )
                                await session.commit()
                                click.echo(
                                    f"Retired registry: {existing.id} ({deleted} items deleted)"
                                )
                            else:
                                click.echo("Registry absent")
                            succeeded.append(registry_name)
                            continue
                        # A platform registry's credentials are a secret of the
                        # platform workspace, named in the manifest and resolved
                        # here to its id: a reference, never the value.
                        secret_ref = config.get("credentials_secret_ref")
                        credentials = (
                            await platform_secret_id(session, str(secret_ref))
                            if secret_ref
                            else None
                        )
                        had_credentials = bool(existing and existing.credentials_secret_ref)
                        if existing:
                            registry_id = existing.id
                            click.echo(f"Found existing registry: {registry_id}")
                            # Reconcile is the only way a manifest edit reaches an
                            # installed platform: every field of the entry is applied.
                            changes = await reconcile_existing_registry(
                                service, existing, config, credentials_secret_ref=credentials
                            )
                            if changes:
                                click.echo(f"Updated {', '.join(changes)}")
                        else:
                            # Detection fetches an index to inspect its shape; the
                            # sync fetches it again to parse. Set `type` to skip it.
                            registry_type = manifest_registry_type(
                                config, service.detect_type_from_source
                            )
                            if not config.get("type"):
                                click.echo(f"Detected type: {registry_type}")
                            registry = await service.create_registry(
                                name=registry_name,
                                registry_type=registry_type,
                                source_type=config.get("source_type", "url"),
                                source_url=config["source_url"],
                                description=config.get("description"),
                                recommendation_priority=config.get("recommendation_priority"),
                                mode=config.get("mode", "mirror"),
                                trust=config.get("trust", "official"),
                                credentials_secret_ref=credentials,
                                source_ref=config.get("source_ref"),
                                source_path=config.get("source_path"),
                            )
                            registry_id = registry.id
                            click.echo(f"Created registry: {registry_id}")
                        if credentials is not None or had_credentials:
                            await record_registry_secret_reference(
                                session, registry_id, credentials
                            )

                        replacements.append(registry_id)
                        stats = await service.sync_registry(registry_id, force=force)
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

    busy: list[str] = []
    if workspace_registries:
        # A tenant's broken source is recorded on its registry and reported
        # here; it does not fail the run the platform's sources decide.
        synced, broken, busy = await _reconcile_workspace_registries(db, force=force)
        click.echo(f"\nWorkspace registries: {len(synced)} synced, {len(broken)} failed")
        for name, err in broken:
            click.echo(f"  - {name}: {err}", err=True)
    for name in (*skipped, *busy):
        click.echo(f"  WARNING: skipped, another reconcile was syncing: {name}", err=True)

    click.echo(
        f"\nReconcile complete: {len(succeeded)} succeeded, {len(failed)} failed, "
        f"{len(skipped)} skipped (out of {len(configs)})"
    )
    if failed:
        for name, err in failed:
            click.echo(f"  - {name}: {err}", err=True)
        sys.exit(1)


@cli.command("dlq-replay")
@click.argument("dlq")
@click.option("--start", default="-", help="First message id to replay, inclusive ('-': oldest).")
@click.option("--end", default="+", help="Last message id to replay, inclusive ('+': newest).")
def dlq_replay(dlq: str, start: str, end: str):
    """Move dead letters from DLQ back to the stream (or partition) each came from.

    Each message is moved once: running it again, or alongside another
    operator, replays nothing twice.
    """
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    asyncio.run(_dlq_replay(dlq, start, end))


async def _dlq_replay(dlq: str, start: str, end: str) -> None:
    # The broker and stream settings alone: the full application Settings
    # also demands Temporal configuration, which an operator's shell has no use for.
    from agentarea_common.broker import RedisStreamsBroker
    from agentarea_common.broker.dlq import replay_dead_letters
    from agentarea_common.broker.routes import configured_routes, routes_for_dlq
    from agentarea_common.config import BrokerSettings, EventStreamSettings, RedisSettings

    broker_type = BrokerSettings().BROKER
    if broker_type != "redis":
        raise click.UsageError(f"dlq-replay needs AGENTAREA_BROKER=redis (current: {broker_type})")
    streams = EventStreamSettings()
    try:
        routes = routes_for_dlq(configured_routes(streams), dlq)
    except LookupError as exc:
        raise click.UsageError(str(exc)) from exc

    broker = RedisStreamsBroker(RedisSettings().REDIS_URL, namespace=streams.NAMESPACE)
    try:
        result = await replay_dead_letters(
            broker,
            dlq_stream=dlq,
            targets=[route.stream for route in routes],
            start=start,
            end=end,
        )
    finally:
        await broker.aclose()
    click.echo(f"Replayed {result.moved} dead letters from {dlq}; {result.skipped} left in place")


async def _reconcile_workspace_registries(
    db: Database, *, force: bool
) -> tuple[list[str], list[tuple[str, str]], list[str]]:
    """Sync every active registry a workspace added, each as its own workspace.

    An unchanged index ETag or repository head is skipped like a platform
    source's. Credentials resolve from the owning workspace's secrets.
    """
    from agentarea_common.auth.context import UserContext
    from agentarea_common.base.tenant_scope import workspace_scope
    from agentarea_common.constants import PLATFORM_PRINCIPAL_ID
    from agentarea_mcp.infrastructure.repository import MCPServerRepository
    from agentarea_registry.application.service import RegistryService
    from agentarea_registry.infrastructure.repository import (
        RegistryItemRepository,
        RegistryRepository,
    )

    from agentarea_api.registry_content import registry_content_mirror
    from agentarea_api.registry_credentials import registry_credentials_resolver

    content_mirror = registry_content_mirror()
    async with db.async_session_factory() as session:
        registries = await RegistryRepository(session).list_active_workspace_registries()
    click.echo(f"\nWorkspace registries: {len(registries)}")

    succeeded: list[str] = []
    failed: list[tuple[str, str]] = []
    skipped: list[str] = []
    for registry in registries:
        label = f"{registry.workspace_id}/{registry.name}"
        click.echo(f"\nReconciling: {label}")
        owner = UserContext(user_id=PLATFORM_PRINCIPAL_ID, workspace_id=str(registry.workspace_id))
        try:
            async with _registry_sync_lock(db, f"registry-sync:{registry.id}") as held:
                if not held:
                    click.echo(f"Skipped {label}: another reconcile is syncing it")
                    skipped.append(label)
                    continue
                with workspace_scope(owner.workspace_id):
                    async with db.async_session_factory() as session:
                        service = RegistryService(
                            RegistryRepository(session, owner),
                            RegistryItemRepository(session, owner),
                            MCPServerRepository(session, owner),
                            credentials_resolver=registry_credentials_resolver(session),
                            content_mirror=content_mirror,
                        )
                        stats = await service.sync_registry(registry.id, force=force)
                        await session.commit()
            click.echo(f"Synced: {stats}")
            succeeded.append(label)
        except Exception as e:
            logger.exception("Reconcile failed for workspace registry %s", label)
            click.echo(f"Reconcile failed for {label}: {e}", err=True)
            failed.append((label, str(e)))
    return succeeded, failed, skipped


if __name__ == "__main__":
    cli()
