"""The phase-4 migration keeps a source's webhook_config an object.

A source stored before it may hold JSON ``null`` in ``webhook_config``; jsonb
``null || {...}`` is an array, which the Go event-service skips and the intake
cannot read as configuration.

Set STREAMS_TEST_DATABASE_URL to a postgresql+asyncpg URL of a disposable
database (scripts/check-db.sh does). The statement runs on a temporary
``stream_sources`` with the pre-migration columns, so the migrated table is
untouched.
"""

from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

TEST_DATABASE_URL = os.getenv("STREAMS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="STREAMS_TEST_DATABASE_URL not set")

MIGRATION = Path(__file__).resolve().parents[1] / "alembic/versions/20261015_1900_phase4_sources.py"


def _webhook_config_statement() -> str:
    spec = importlib.util.spec_from_file_location("_phase4_sources", MIGRATION)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    op = MagicMock()
    with patch.object(module, "op", op):
        module.upgrade()
    [statement] = [
        str(call.args[0])
        for call in op.execute.call_args_list
        if "SET webhook_config" in str(call.args[0])
    ]
    return statement


async def test_a_null_webhook_config_becomes_an_object() -> None:
    statement = _webhook_config_statement()
    engine = create_async_engine(TEST_DATABASE_URL)
    try:
        async with engine.connect() as conn:
            await conn.execute(
                text(
                    "CREATE TEMP TABLE stream_sources "
                    "(id int, webhook_config json, validation_rules json)"
                )
            )
            await conn.execute(
                text(
                    "INSERT INTO stream_sources VALUES "
                    "(1, 'null'::json, NULL), "
                    '(2, NULL, \'{"signature_header": "X-Sig"}\'::json), '
                    '(3, \'{"shop_id": "7"}\'::json, \'{"signature_prefix": "sha256="}\'::json)'
                )
            )
            await conn.execute(text(statement))
            rows = (
                await conn.execute(
                    text("SELECT id, webhook_config::text FROM stream_sources ORDER BY id")
                )
            ).all()
            await conn.rollback()
    finally:
        await engine.dispose()

    assert [(row[0], json.loads(row[1])) for row in rows] == [
        (1, {}),
        (2, {"header": "X-Sig"}),
        (3, {"shop_id": "7", "prefix": "sha256="}),
    ]
