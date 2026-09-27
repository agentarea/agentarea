"""What the ORM does with a workspace-scoped query, by mode and by scope.

The per-model isolation matrix lives in ``tests/unit/test_tenant_scope_isolation.py``;
this pins the mechanism: a bound scope filters, ``unscoped`` bypasses with a
reason, and a query with neither is refused in ``enforce`` and let through with
one warning per call site in ``log``.
"""

import logging
from collections.abc import AsyncIterator

import pytest
from agentarea_common.base.models import WorkspaceScopedMixin
from agentarea_common.base.tenant_scope import (
    UnscopedQueryError,
    current_workspace_scope,
    tenant_scoped_session_class,
    unscoped,
    workspace_scope,
)
from agentarea_common.config.database import (
    Database,
    TenantScopeMode,
    TenantScopeSettings,
    get_database,
)
from pydantic import ValidationError
from sqlalchemy import String, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class _Base(DeclarativeBase):
    pass


class _Note(_Base, WorkspaceScopedMixin):
    __tablename__ = "tenant_scope_notes"

    id: Mapped[int] = mapped_column(primary_key=True)
    body: Mapped[str] = mapped_column(String)


class _Unscoped(_Base):
    __tablename__ = "tenant_scope_plain"

    id: Mapped[int] = mapped_column(primary_key=True)


async def _sessions(mode: TenantScopeMode) -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(_Base.metadata.create_all)
    sessions = async_sessionmaker(
        engine, sync_session_class=tenant_scoped_session_class(mode), expire_on_commit=False
    )
    async with sessions() as session:
        session.add_all(
            [
                _Note(id=1, body="a", workspace_id="ws-a", created_by="u"),
                _Note(id=2, body="b", workspace_id="ws-b", created_by="u"),
            ]
        )
        await session.commit()
    return sessions


@pytest.fixture
async def enforcing() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield await _sessions(TenantScopeMode.ENFORCE)


@pytest.fixture
async def logging_only() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    yield await _sessions(TenantScopeMode.LOG)


async def _bodies(session: AsyncSession) -> list[str]:
    return sorted((await session.execute(select(_Note.body))).scalars())


async def test_a_bound_scope_filters(enforcing) -> None:
    async with enforcing() as session:
        with workspace_scope("ws-a"):
            assert await _bodies(session) == ["a"]
        with workspace_scope("ws-b"):
            assert await _bodies(session) == ["b"]


async def test_enforce_refuses_a_query_with_no_scope(enforcing) -> None:
    async with enforcing() as session:
        with pytest.raises(UnscopedQueryError, match="_Note"):
            await _bodies(session)


async def test_unscoped_models_need_no_scope(enforcing) -> None:
    async with enforcing() as session:
        assert (await session.execute(select(_Unscoped))).all() == []


async def test_unscoped_spans_workspaces(enforcing) -> None:
    async with enforcing() as session:
        with unscoped("the test reads both workspaces on purpose"):
            assert await _bodies(session) == ["a", "b"]


@pytest.mark.parametrize("reason", ["", "   "])
def test_unscoped_needs_a_reason(reason: str) -> None:
    with pytest.raises(ValueError, match="reason"), unscoped(reason):
        pass


def test_a_scope_needs_a_workspace() -> None:
    with pytest.raises(ValueError, match="workspace id"), workspace_scope(""):
        pass


def test_scopes_nest_and_restore() -> None:
    assert current_workspace_scope() is None
    with workspace_scope("ws-a"):
        with unscoped("nested bypass"):
            assert current_workspace_scope() is None
        with workspace_scope("ws-b"):
            assert current_workspace_scope() == "ws-b"
        assert current_workspace_scope() == "ws-a"
    assert current_workspace_scope() is None


async def test_log_mode_runs_unfiltered_and_warns_once_per_call_site(
    logging_only, caplog
) -> None:
    caplog.set_level(logging.WARNING, logger="agentarea_common.base.tenant_scope")
    async with logging_only() as session:
        for _ in range(3):
            assert await _bodies(session) == ["a", "b"]

    warnings = [r for r in caplog.records if "Unscoped ORM query" in r.getMessage()]
    assert len(warnings) == 1
    assert "_Note" in warnings[0].getMessage()
    assert "test_tenant_scope.py" in warnings[0].getMessage()


def test_the_mode_is_required(monkeypatch) -> None:
    monkeypatch.delenv("AGENTAREA_DB_TENANT_SCOPE", raising=False)
    with pytest.raises(ValidationError):
        TenantScopeSettings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_the_mode_rejects_anything_else(monkeypatch) -> None:
    monkeypatch.setenv("AGENTAREA_DB_TENANT_SCOPE", "off")
    with pytest.raises(ValidationError):
        TenantScopeSettings(_env_file=None)  # pyright: ignore[reportCallIssue]


def test_the_application_sessions_are_scoped() -> None:
    database: Database = get_database()
    for factory in (database.async_session_factory, database.read_session_factory):
        session_class = factory.kw["sync_session_class"]
        assert session_class.__name__ == "TenantScopedSession"
