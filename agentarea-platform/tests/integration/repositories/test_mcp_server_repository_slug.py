"""Integration tests for MCPServerRepository.get_by_slug (workspace-scoped)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_common.auth.context import UserContext
from agentarea_mcp.application.service import MCPServerInstanceService
from agentarea_mcp.domain.models import MCPServer
from agentarea_mcp.infrastructure.repository import MCPServerRepository
from agentarea_mcp.schemas.dto import MCPServerInstanceCreate
from sqlalchemy import select
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
    return UserContext(user_id=user_id, workspace_id=workspace_id)


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


class TestServiceSpecCreatePopulatesSlug:
    """Regression: service paths that persist MCPServer specs must set the NOT NULL
    ``slug`` against a real DB.

    The Vercel "connect built-in catalog MCP" flow raised
    ``NotNullViolationError`` because ``_materialize_workspace_spec_copy`` (and the
    sibling ``_auto_create_spec_for_instance``) built ``MCPServer(...)`` and did a
    direct ``session.add`` + ``flush``, bypassing the repository's slug resolver.
    Mocked-session unit tests can't enforce NOT NULL, so these tests drive the real
    service methods against the SQLite ``mcp_servers`` table, where a missing slug
    fails the INSERT exactly as Postgres did.
    """

    def _make_service(self, session: AsyncSession, ctx: UserContext) -> MCPServerInstanceService:
        svc = MCPServerInstanceService.__new__(MCPServerInstanceService)
        # Only the collaborators the spec-creation paths touch: a session/context
        # carrier and the real MCP server repository (its resolve_unique_slug does
        # the workspace-scoped uniqueness query against the live table).
        svc.repository = SimpleNamespace(session=session, user_context=ctx)
        svc.mcp_server_repository = MCPServerRepository(session, ctx)
        return svc

    @pytest.mark.asyncio
    async def test_materialize_workspace_spec_copy_persists_with_slug(
        self, slug_db_session: AsyncSession
    ):
        ctx = _ctx(workspace_id="ws-a", user_id="user-a")
        svc = self._make_service(slug_db_session, ctx)

        # A catalog/platform source spec owned by another workspace (as the Vercel
        # remote-OAuth entry is). Only its attributes are read by the copy path.
        source = SimpleNamespace(
            name="Vercel",
            description="Remote MCP server for Vercel.",
            docker_image_url=None,
            version="1.0.0",
            tags=["registry", "url", "streamable-http"],
            env_schema=[],
            cmd=None,
            remote_url="https://mcp.vercel.com",
            registry_item_id=uuid4(),
            json_spec={"name": "ai.agentarea.catalog/vercel"},
            registry_url="https://example.com/mcp-remote-oauth-registry.json",
        )

        # Would raise IntegrityError (NOT NULL slug) before the fix.
        copy = await svc._materialize_workspace_spec_copy(source)

        assert copy.slug == "vercel"
        assert copy.workspace_id == "ws-a"
        assert copy.created_by == "user-a"

        persisted = (
            await slug_db_session.execute(select(MCPServer).where(MCPServer.id == copy.id))
        ).scalar_one()
        assert persisted.slug == "vercel"

    @pytest.mark.asyncio
    async def test_materialize_twice_gets_unique_slug(self, slug_db_session: AsyncSession):
        ctx = _ctx(workspace_id="ws-a", user_id="user-a")
        svc = self._make_service(slug_db_session, ctx)
        source = SimpleNamespace(
            name="Vercel",
            description="Remote MCP server for Vercel.",
            docker_image_url=None,
            version="1.0.0",
            tags=[],
            env_schema=[],
            cmd=None,
            remote_url="https://mcp.vercel.com",
            registry_item_id=None,
            json_spec=None,
            registry_url=None,
        )

        first = await svc._materialize_workspace_spec_copy(source)
        second = await svc._materialize_workspace_spec_copy(source)

        assert first.slug == "vercel"
        assert second.slug == "vercel-2"

    @pytest.mark.asyncio
    async def test_auto_create_spec_for_instance_persists_with_slug(
        self, slug_db_session: AsyncSession
    ):
        ctx = _ctx(workspace_id="ws-a", user_id="user-a")
        svc = self._make_service(slug_db_session, ctx)

        payload = MCPServerInstanceCreate.model_construct(
            name="My Server",
            description="auto-created spec",
            server_spec_id="",
            json_spec={"type": "docker", "image": "img:latest"},
            auth_config_id=None,
        )

        server = await svc._auto_create_spec_for_instance(payload)

        assert server.slug == "my-server"
        persisted = (
            await slug_db_session.execute(select(MCPServer).where(MCPServer.id == server.id))
        ).scalar_one()
        assert persisted.slug == "my-server"
