"""Integration tests for MCPServerRepository.get_by_slug (workspace-scoped)."""

import pytest
import pytest_asyncio
from agentarea_common.auth.context import UserContext
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.infrastructure.repository import MCPServerRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool


@pytest_asyncio.fixture(scope="function")
async def slug_test_engine():
    """In-memory SQLite engine with ONLY the mcp_servers table.

    We avoid BaseModel.metadata.create_all because some sibling models
    rely on PostgreSQL-only types (e.g. JSONB) that SQLite cannot render.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
        echo=False,
    )

    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: MCPServer.__table__.create(sync_conn, checkfirst=True)
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
    return UserContext(user_id=user_id, workspace_id=workspace_id, roles=["user"])


class TestMCPServerRepositoryGetBySlug:
    @pytest.mark.asyncio
    async def test_get_by_slug_returns_server(self, slug_db_session: AsyncSession):
        ctx = _ctx()
        repo = MCPServerRepository(slug_db_session, ctx)

        created = await repo.create(
            name="My MCP",
            slug="my-mcp",
            description="A test MCP",
            version="1.0.0",
            tags=[],
            status="active",
            is_public=False,
            env_schema=[],
        )

        retrieved = await repo.get_by_slug("my-mcp")
        assert retrieved is not None
        assert retrieved.id == created.id
        assert retrieved.slug == "my-mcp"

    @pytest.mark.asyncio
    async def test_get_by_slug_other_workspace_returns_none(
        self, slug_db_session: AsyncSession
    ):
        ws_a = _ctx(workspace_id="ws-a", user_id="user-a")
        ws_b = _ctx(workspace_id="ws-b", user_id="user-b")

        repo_a = MCPServerRepository(slug_db_session, ws_a)
        repo_b = MCPServerRepository(slug_db_session, ws_b)

        await repo_a.create(
            name="Workspace A Server",
            slug="shared",
            description="Workspace A only",
            version="1.0.0",
            tags=[],
            status="active",
            is_public=False,
            env_schema=[],
        )

        assert await repo_b.get_by_slug("shared") is None

    @pytest.mark.asyncio
    async def test_get_by_slug_unknown_returns_none(self, slug_db_session: AsyncSession):
        repo = MCPServerRepository(slug_db_session, _ctx())
        assert await repo.get_by_slug("does-not-exist") is None
