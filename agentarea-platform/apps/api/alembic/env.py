import re
from datetime import datetime
from logging.config import fileConfig

from agentarea_common.artifacts import ArtifactEvent  # noqa: F401
from agentarea_common.base.models import BaseModel
from agentarea_common.config import get_db_settings
from agentarea_common.events.outbox_orm import EventOutbox  # noqa: F401
from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all ORM models to ensure they're registered with metadata
try:
    from agentarea_triggers.infrastructure.orm import TriggerExecutionORM, TriggerORM  # noqa: F401
except ImportError:
    # Triggers library not yet installed - skip for now
    pass

try:
    from agentarea_governance.infrastructure.orm import (  # noqa: F401
        PolicyRuleORM,
    )
except ImportError:
    # Governance library not yet installed - skip for now
    pass

try:
    from agentarea_bundles.domain.models import InstalledBundle  # noqa: F401
except ImportError:
    # Bundles library not yet installed - skip for now
    pass

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = BaseModel.metadata


def get_url():
    settings = get_db_settings()
    return settings.sync_url


# alembic_version.version_num is VARCHAR(32). Auto-derive every revision id from
# the <date>_<time>_<slug> convention (matching alembic.ini file_template) and cap
# it at 32 chars so a long migration message can never overflow the column again.
_MAX_REVISION_LEN = 32


def process_revision_directives(context, revision, directives):
    for script in directives:
        slug = re.sub(r"\W+", "_", (script.message or "migration").lower()).strip("_")
        rev_id = f"{datetime.now():%Y%m%d_%H%M}_{slug}"[:_MAX_REVISION_LEN].rstrip("_")
        script.rev_id = rev_id


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        process_revision_directives=process_revision_directives,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section)
    configuration["sqlalchemy.url"] = get_url()
    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            process_revision_directives=process_revision_directives,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
