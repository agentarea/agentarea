"""The ledger backfill turns stored paid events into one line each.

Set TASKS_TEST_DATABASE_URL. Runs the migration's own SQL on events written
after the database was migrated; the statements are idempotent.
"""

import importlib.util
import json
import os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

TEST_DATABASE_URL = os.getenv("TASKS_TEST_DATABASE_URL", "")
pytestmark = pytest.mark.skipif(not TEST_DATABASE_URL, reason="TASKS_TEST_DATABASE_URL not set")

MIGRATION = (
    Path(__file__).resolve().parents[3] / "apps/api/alembic/versions/20261008_1200_cost_entries.py"
)


def _migration():
    spec = importlib.util.spec_from_file_location("cost_entries", MIGRATION)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
async def session():
    engine = create_async_engine(TEST_DATABASE_URL)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as session:
        yield session
        await session.rollback()
    await engine.dispose()


async def _event(session: AsyncSession, workspace_id: str, task_id, event_type: str, data: dict):
    event_id = uuid4()
    await session.execute(
        text(
            "INSERT INTO task_events (id, workspace_id, created_by, task_id, event_type, "
            "timestamp, data, event_metadata) VALUES (:id, :ws, 'writer', :task, :type, "
            "now(), CAST(:data AS jsonb), '{}'::jsonb)"
        ),
        {
            "id": event_id,
            "ws": workspace_id,
            "task": task_id,
            "type": event_type,
            "data": json.dumps(data),
        },
    )
    return event_id


async def test_paid_events_become_lines_once_and_free_ones_none(session):
    workspace_id, task_id, agent_id = str(uuid4()), uuid4(), uuid4()
    await session.execute(
        text(
            "INSERT INTO tasks (id, workspace_id, created_by, agent_id, description, status, "
            "created_at, updated_at) VALUES (:id, :ws, 'writer', :agent, 'run', 'completed', "
            "now(), now())"
        ),
        {"id": task_id, "ws": workspace_id, "agent": agent_id},
    )
    llm = await _event(
        session,
        workspace_id,
        task_id,
        "llm.call.completed",
        {
            "cost": 0.5,
            "provider_cost_usd": "0.006",
            "model_id": "m-1",
            "model_name": "kimi-k3",
            "managed_by": "platform",
            "usage": {"usage": {"prompt_tokens": 90, "completion_tokens": 10}},
        },
    )
    await _event(session, workspace_id, task_id, "llm.call.completed", {"cost": "0"})
    await _event(session, workspace_id, task_id, "llm.call.completed", {"cost": "n/a"})
    tool = await _event(
        session,
        workspace_id,
        task_id,
        "tool.result",
        {
            "tool_name": "fetch_report",
            "tool_call_id": "call-1",
            "model_cost": "2",
            "service_cost": "0.25",
            "payment": {"protocol": "x402", "tx_hash": "0xabc", "response_body": "big"},
        },
    )

    for _ in range(2):
        for statement in _migration().BACKFILL_SQL:
            await session.execute(text(statement))

    rows = (
        await session.execute(
            text(
                "SELECT event_id, category, agent_id, amount, currency, source, subject_name, "
                "call_ref, evidence FROM cost_entries WHERE workspace_id = :ws "
                "ORDER BY amount"
            ),
            {"ws": workspace_id},
        )
    ).fetchall()
    assert [(r.event_id, r.category, r.amount, r.currency, r.source) for r in rows] == [
        (tool, "service", Decimal("0.25"), "USD", "x402"),
        (llm, "model", Decimal("0.5"), None, "token_pricing"),
        (tool, "model", Decimal("2"), None, "tool_reported"),
    ]
    assert {r.agent_id for r in rows} == {agent_id}
    service, model_call, _ = rows
    assert service.evidence["payment"] == {"protocol": "x402", "tx_hash": "0xabc"}
    assert (service.subject_name, service.call_ref) == ("fetch_report", "call-1")
    assert model_call.evidence == {"prompt_tokens": 90, "completion_tokens": 10}
