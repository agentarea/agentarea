from logging.config import fileConfig

from agentarea_common.base.models import BaseModel
from agentarea_common.config import get_db_settings
from alembic import context
from sqlalchemy import engine_from_config, pool

# Import all ORM models to ensure they're registered with metadata
try:
    from agentarea_triggers.infrastructure.orm import TriggerExecutionORM, TriggerORM  # noqa: F401
except ImportError:
    # Triggers library not yet installed - skip for now
    pass

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = BaseModel.metadata


def get_url():
    settings = get_db_settings()
    return settings.sync_url


def run_migrations_offline() -> None:
    url = get_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
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
        context.configure(connection=connection, target_metadata=target_metadata)

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
