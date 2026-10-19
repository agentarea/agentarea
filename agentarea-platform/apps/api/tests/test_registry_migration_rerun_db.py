"""The ADR-0044 catalog migrations survive the rollout hook being killed or refused a lock.

The migration hook has a deadline and retries. A run that stops partway must
leave the database where a rerun picks up: never a committed column whose
revision is unstamped (the rerun then fails on DuplicateColumn and the sync is
wedged), and never a half-swapped index the next run trips over. A migration
that cannot get its lock gives up within ``lock_timeout`` instead of queueing
every catalog read behind itself.

Runs the real alembic environment against the check-db database
(``AGENTAREA_DB_*``), and leaves it at head.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

TEST_DATABASE_URL = os.getenv("CATALOG_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(
    not (TEST_DATABASE_URL and os.getenv("AGENTAREA_DB_HOST")),
    reason="CATALOG_TEST_DATABASE_URL and AGENTAREA_DB_* not set",
)

API_DIR = Path(__file__).resolve().parents[1]
BEFORE_CATALOG = "20261013_2200_drop_decide"
SCHEMA = "20261019_1500_registry_scope"
COUNT_INDEXES = ("ix_registry_items_browse_name", "ix_registry_items_browse_facets")


@pytest.fixture
def alembic_config(monkeypatch) -> Config:
    monkeypatch.chdir(API_DIR)
    config = Config(str(API_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(API_DIR / "alembic"))
    yield config
    command.upgrade(config, "head")


@pytest.fixture
def engine():
    eng = create_engine(make_url(TEST_DATABASE_URL).set(drivername="postgresql"))
    yield eng
    eng.dispose()


def _revision(engine) -> str:
    with engine.connect() as conn:
        return conn.execute(text("SELECT version_num FROM alembic_version")).scalar_one()


def _count_indexes(engine) -> dict[str, str]:
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT indexname, indexdef FROM pg_indexes "
                "WHERE tablename = 'registry_items' AND indexname LIKE 'ix_registry_items_browse_%'"
            )
        )
        return dict(rows.tuples().all())


def test_an_index_swap_killed_between_drop_and_rename_resumes(alembic_config, engine):
    command.downgrade(alembic_config, SCHEMA)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as conn:
        conn.execute(text("DROP INDEX ix_registry_items_browse_name"))
        conn.execute(
            text("CREATE INDEX ix_registry_items_browse_name_next ON registry_items (registry_type)")
        )

    command.upgrade(alembic_config, "head")

    indexes = _count_indexes(engine)
    assert {name for name in indexes if name in COUNT_INDEXES} == set(COUNT_INDEXES)
    assert not any(name.endswith("_next") for name in indexes)
    assert all("registry_workspace_id" in indexes[name] for name in COUNT_INDEXES)


def test_a_refused_lock_rolls_the_catalog_schema_back_whole(alembic_config, engine):
    command.downgrade(alembic_config, BEFORE_CATALOG)
    holder = engine.connect()
    try:
        # An in-flight write on the table 1500's foreign key locks: 1200 has
        # already added its column in the same transaction when 1500 gives up.
        holder.execute(text("LOCK TABLE encrypted_secrets IN ROW EXCLUSIVE MODE"))
        with pytest.raises(OperationalError, match="lock timeout"):
            command.upgrade(alembic_config, "head")
    finally:
        holder.rollback()
        holder.close()

    assert _revision(engine) == BEFORE_CATALOG
    with engine.connect() as conn:
        columns = conn.execute(
            text(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_name = 'registries' AND column_name IN ('source_etag', 'scope')"
            )
        ).scalars()
        assert list(columns) == []

    command.upgrade(alembic_config, "head")

    assert _revision(engine) == ScriptDirectory.from_config(alembic_config).get_current_head()
