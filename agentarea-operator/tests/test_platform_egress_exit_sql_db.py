"""PlatformEgressExit's raw SQL, run against the real migrated schema.

Same reason as test_platform_connection_sql_db: the columns belong to a model in
another package, and nothing else would notice one drifting.
"""

from __future__ import annotations

import os

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, text  # noqa: E402

DSN = os.environ.get("OPERATOR_TEST_DATABASE_URL", "")

if not DSN and os.environ.get("OPERATOR_REQUIRE_DB") == "1":
    raise RuntimeError(
        "OPERATOR_REQUIRE_DB=1 but OPERATOR_TEST_DATABASE_URL is unset: the schema "
        "checks would have been skipped silently."
    )

pytestmark = pytest.mark.skipif(not DSN, reason="OPERATOR_TEST_DATABASE_URL is not set")

NAME = "operator-test-exit"


@pytest.fixture
def handler(monkeypatch):
    import handler as module

    engine = create_engine(DSN, pool_pre_ping=True)
    monkeypatch.setattr(module, "engine", engine)
    try:
        yield module
    finally:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM egress_exits WHERE name = :n"), {"n": NAME})
        engine.dispose()


def _row(module, exit_id):
    with module.engine.begin() as conn:
        return conn.execute(
            text(
                "SELECT workspace_id, managed_by, via, remote_dns, upstream_url, updated_at "
                "FROM egress_exits WHERE id = :id"
            ),
            {"id": exit_id},
        ).one()


def test_a_platform_exit_lands_in_the_platform_workspace_under_its_derived_id(handler):
    exit_id = handler.sync_platform_egress_exit({"name": NAME, "via": "hop-a", "remoteDns": True})

    row = _row(handler, exit_id)
    assert exit_id == handler.platform_egress_exit_id(NAME)
    assert (row.workspace_id, row.managed_by, row.via, row.remote_dns, row.upstream_url) == (
        "platform",
        "platform",
        "hop-a",
        True,
        None,
    )


def test_a_reconcile_of_an_unchanged_exit_writes_nothing_and_a_change_lands(handler):
    exit_id = handler.sync_platform_egress_exit({"name": NAME, "via": "hop-a"})
    first = _row(handler, exit_id)

    handler.sync_platform_egress_exit({"name": NAME, "via": "hop-a"})
    assert _row(handler, exit_id).updated_at == first.updated_at

    handler.sync_platform_egress_exit({"name": NAME, "via": "other-hop"})
    assert _row(handler, exit_id).via == "other-hop"
