"""Integration tests for AgentRepository.get_by_slug (workspace-scoped)."""

from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_agents.domain.models import Agent
from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_common.auth.context import UserContext
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture(scope="function")
async def slug_test_engine():
    """Create an in-memory SQLite engine with ONLY the agents table.

    We do not run BaseModel.metadata.create_all because some sibling models
    rely on PostgreSQL-only types (e.g. JSONB) that SQLite cannot render.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    async with engine.begin() as conn:
        # Skill association table is referenced by Agent.skills relationship —
        # create just the agents table by passing tables= directly.
        await conn.run_sync(
            lambda sync_conn: Agent.__table__.create(sync_conn, checkfirst=True)
        )

    yield engine

    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def slug_db_session(slug_test_engine):
    async_session = async_sessionmaker(
        slug_test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


def _ctx(workspace_id: str = "ws-a", user_id: str = "user-a") -> UserContext:
    return UserContext(user_id=user_id, workspace_id=workspace_id)


class TestAgentRepositoryGetBySlug:
    @pytest.mark.asyncio
    async def test_get_by_slug_returns_agent(self, slug_db_session: AsyncSession):
        ctx = _ctx()
        repo = AgentRepository(slug_db_session, ctx)

        created = await repo.create(
            name="My Agent",
            slug="my-agent",
            status="active",
            model_id=str(uuid4()),
        )

        retrieved = await repo.get_by_slug("my-agent")
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.slug == "my-agent"

    @pytest.mark.asyncio
    async def test_get_by_slug_other_workspace_returns_none(
        self, slug_db_session: AsyncSession
    ):
        ws_a = _ctx(workspace_id="ws-a", user_id="user-a")
        ws_b = _ctx(workspace_id="ws-b", user_id="user-b")

        repo_a = AgentRepository(slug_db_session, ws_a)
        repo_b = AgentRepository(slug_db_session, ws_b)

        await repo_a.create(
            name="Workspace A Agent",
            slug="shared",
            status="active",
            model_id=str(uuid4()),
        )

        # Same slug, but other workspace must NOT see it.
        assert await repo_b.get_by_slug("shared") is None

    @pytest.mark.asyncio
    async def test_get_by_slug_unknown_returns_none(self, slug_db_session: AsyncSession):
        repo = AgentRepository(slug_db_session, _ctx())
        assert await repo.get_by_slug("does-not-exist") is None
