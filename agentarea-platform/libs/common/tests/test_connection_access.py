"""A connection is created personal and shared with the workspace only on purpose."""

from datetime import datetime
from uuid import UUID, uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import WorkspaceScopedMixin
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.rebac.connection_access import (
    lend_connection,
    make_personal,
    personal_connection_ids,
    share_with_workspace,
    withdraw_connection,
)
from agentarea_common.rebac.models import RelationTuple
from agentarea_common.testing import install_graph_ownership_stub
from sqlalchemy import DateTime, String, Uuid
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


# Its own registry: a graph-governed model in the shared one would count as a real one.
class _Base(DeclarativeBase):
    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now)


class _Connection(_Base, WorkspaceScopedMixin):
    __tablename__ = "test_personal_connections"
    __graph_resource__ = True
    __graph_personal__ = True

    managed_by: Mapped[str | None] = mapped_column(String(32), nullable=True)


@pytest.fixture
def graph(monkeypatch):
    return install_graph_ownership_stub(monkeypatch)


def _personal(connection_id) -> set[str]:
    return {f"resource:{connection_id}#personal@{s}" for s in ("User:*", "Agent:*")}


def _written(graph) -> set[str]:
    return {str(t) for t in graph.recorded}


async def test_personal_names_every_caller_and_sharing_removes_it(graph):
    connection_id = uuid4()

    await make_personal(connection_id)
    assert _written(graph) == _personal(connection_id)
    assert await personal_connection_ids([connection_id, uuid4()]) == {str(connection_id)}

    await share_with_workspace(connection_id)
    assert graph.recorded == []
    assert await personal_connection_ids([connection_id]) == set()


async def test_a_loan_names_the_agent_and_is_withdrawn(graph):
    connection_id, agent_id = uuid4(), uuid4()

    await lend_connection(connection_id, agent_id)
    assert graph.recorded == [
        RelationTuple(
            namespace="resource",
            object=str(connection_id),
            relation="connection_user",
            subject_id=f"Agent:{agent_id}",
        )
    ]

    await withdraw_connection(connection_id, agent_id)
    assert graph.recorded == []


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: _Base.metadata.create_all(c, tables=[_Connection.__table__]))
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    try:
        async with factory() as s:
            yield s
    finally:
        await engine.dispose()


async def test_a_new_connection_is_its_creators_and_a_platform_one_is_not(graph, session):
    repository = WorkspaceScopedRepository(
        session, _Connection, UserContext(user_id="u1", workspace_id="ws1")
    )

    mine = await repository.create()
    platform = await repository.create(managed_by="platform")

    assert await personal_connection_ids([mine.id, platform.id]) == {str(mine.id)}
    assert _personal(mine.id) <= _written(graph)
