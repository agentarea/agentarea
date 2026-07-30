"""Task spend aggregation must count delegated model calls exactly once."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy.dialects import postgresql


@pytest.mark.asyncio
async def test_spend_uses_own_cost_with_total_cost_as_history_fallback():
    session = MagicMock()
    result = MagicMock()
    result.scalar.return_value = 0
    session.execute = AsyncMock(return_value=result)
    repository = TaskRepository(
        session,
        UserContext(user_id="alice", workspace_id="workspace-1"),
    )

    await repository.sum_spend_since(datetime.now(UTC).replace(tzinfo=None))

    statement = session.execute.await_args.args[0]
    sql = str(
        statement.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    assert "own_cost" in sql
    assert "total_cost" in sql
    assert "coalesce" in sql.lower()
