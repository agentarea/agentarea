"""Task spend is summed from the ledger, where each paid line is stored once."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy.dialects import postgresql


def _repository() -> tuple[TaskRepository, MagicMock]:
    session = MagicMock()
    session.scalar = AsyncMock(return_value=0)
    return TaskRepository(
        session, UserContext(user_id="alice", workspace_id="workspace-1")
    ), session


def _sql(session: MagicMock) -> str:
    statement = session.scalar.await_args.args[0]
    return str(
        statement.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
    )


@pytest.mark.asyncio
async def test_spend_sums_current_ledger_lines_in_the_billing_currency():
    repository, session = _repository()

    await repository.sum_spend_since(datetime(2026, 10, 1, tzinfo=UTC))

    sql = _sql(session)
    assert "FROM cost_entries" in sql
    assert "supersedes_id" in sql
    assert "currency = 'USD'" in sql
    assert "agent_id" not in sql.split("WHERE", 1)[1]


@pytest.mark.asyncio
async def test_agent_spend_is_narrowed_to_the_agent():
    repository, session = _repository()
    agent_id = uuid4()

    await repository.sum_spend_mtd(agent_id=agent_id)

    assert f"agent_id = '{agent_id}'" in _sql(session)
