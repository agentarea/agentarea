"""Regression guards for the single, unified database engine.

Background: the codebase used to have two separate ``Database`` classes
(``config.database`` and ``infrastructure.database``), each building its own
connection pool. Their pool configuration drifted — neither enabled
``pool_pre_ping`` — so a connection reaped server-side was handed out dead and
asyncpg raised "the underlying connection is closed", surfacing as intermittent
500s (e.g. the /workplace "Failed to load agents" error).

These tests pin the consolidated behaviour: one engine source, with liveness
checking enabled on every pool. Building an engine does not open a connection,
so these run without a live database.
"""

import inspect

import pytest


def test_old_infrastructure_module_is_gone():
    """The second engine module must not come back."""
    with pytest.raises(ModuleNotFoundError):
        __import__("agentarea_common.infrastructure.database")


def test_single_database_instance():
    from agentarea_common.config.database import db, get_database

    assert get_database() is get_database()
    assert db is get_database()


def test_all_pools_have_pre_ping_enabled():
    """Every pool must verify connection liveness on checkout."""
    from agentarea_common.config.database import get_database

    database = get_database()
    for name in ("engine", "read_engine", "sync_engine"):
        engine = getattr(database, name)
        assert engine.pool._pre_ping is True, f"{name} pool is missing pool_pre_ping"


def test_all_pools_recycle_connections():
    from agentarea_common.config.database import get_database

    database = get_database()
    expected = database.settings.pool_recycle
    for name in ("engine", "read_engine", "sync_engine"):
        engine = getattr(database, name)
        assert engine.pool._recycle == expected, f"{name} pool is missing pool_recycle"


def test_session_dependencies_are_async_generators():
    """FastAPI session dependencies must be async generators (yield-based)."""
    from agentarea_common.config.database import get_db_session, get_read_db_session

    assert inspect.isasyncgenfunction(get_db_session)
    assert inspect.isasyncgenfunction(get_read_db_session)


def test_session_context_managers_exist():
    from agentarea_common.config.database import Database, get_database

    database = get_database()
    # Write (transactional) and read (AUTOCOMMIT) context managers, plus the
    # historical ``get_db`` alias, must all be present.
    assert hasattr(database, "session")
    assert hasattr(database, "read_session")
    # ``get_db`` is an alias of ``session`` (same underlying function on the
    # class; instance access produces distinct bound-method objects).
    assert Database.get_db is Database.session
