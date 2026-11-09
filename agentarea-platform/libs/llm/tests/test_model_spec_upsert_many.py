"""Discovery writes a provider's whole model list in a fixed number of statements.

It used to write one model at a time: an admin check, three lookups, an insert
and a commit each. OpenRouter lists ~570 runnable models, which took ten
seconds, and the webapp gives a server action eight, so discovering models
failed every time while the rows kept landing behind the aborted request.
"""

from decimal import Decimal
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig, ProviderSpec
from agentarea_llm.infrastructure.model_spec_repository import ModelSpecRepository
from agentarea_secrets.models import EncryptedSecret
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

PROVIDER_SPEC_ID = uuid4()
WORKSPACE = "ws-a"


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    event.listen(
        engine.sync_engine,
        "connect",
        lambda dbapi_connection, _record: dbapi_connection.execute("PRAGMA foreign_keys=ON"),
    )
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[
                    EncryptedSecret.__table__,
                    ProviderSpec.__table__,
                    ProviderConfig.__table__,
                    ModelSpec.__table__,
                    ModelInstance.__table__,
                ],
            )
        )
    async with AsyncSession(engine) as session:
        session.add(
            ProviderSpec(
                id=PROVIDER_SPEC_ID,
                provider_key="openrouter",
                name="OpenRouter",
                provider_type="openrouter",
                workspace_id="platform",
                created_by="test",
            )
        )
        await session.commit()
    try:
        yield engine
    finally:
        await engine.dispose()


def _row(name: str, price: str | None = "0.000001", **overrides) -> dict:
    return {
        "model_name": name,
        "display_name": name.upper(),
        "description": None,
        "kind": "chat",
        "context_window": 8192,
        "max_output_tokens": None,
        "input_cost_per_token": None if price is None else Decimal(price),
        "output_cost_per_token": None if price is None else Decimal(price),
        "supports_function_calling": True,
        "supports_vision": False,
        "supports_reasoning": False,
        **overrides,
    }


async def _upsert(engine, rows: list[dict], workspace: str = WORKSPACE):
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        repo = ModelSpecRepository(session, UserContext(user_id="admin", workspace_id=workspace))
        return await repo.upsert_many_by_provider_and_model(PROVIDER_SPEC_ID, rows)


async def _rows(engine) -> dict[tuple[str, str], ModelSpec]:
    async with AsyncSession(engine) as session:
        return {
            (spec.workspace_id, spec.model_name): spec
            for spec in (await session.execute(select(ModelSpec))).scalars()
        }


@pytest.mark.asyncio
async def test_new_models_are_inserted_and_reported_new(engine):
    written = await _upsert(engine, [_row("a"), _row("b")])

    rows = await _rows(engine)
    assert {name for _, name in rows} == {"a", "b"}
    assert {name: w.is_new for name, w in written.items()} == {"a": True, "b": True}
    assert written["a"].id == rows[(WORKSPACE, "a")].id
    assert rows[(WORKSPACE, "a")].created_by == "admin"


@pytest.mark.asyncio
async def test_rediscovery_updates_the_row_and_keeps_what_the_provider_no_longer_reports(engine):
    first = await _upsert(engine, [_row("a", description="kept")])
    again = await _upsert(engine, [_row("a", price="0.000002", description=None)])

    spec = (await _rows(engine))[(WORKSPACE, "a")]
    assert again["a"].id == first["a"].id
    assert again["a"].is_new is False
    assert spec.input_cost_per_token == Decimal("0.000002")
    assert spec.description == "kept"


@pytest.mark.asyncio
async def test_another_workspaces_row_is_neither_matched_nor_touched(engine):
    other = await _upsert(engine, [_row("a", price="0")], workspace="ws-b")
    mine = await _upsert(engine, [_row("a")])

    rows = await _rows(engine)
    assert mine["a"].is_new is True
    assert mine["a"].id != other["a"].id
    assert rows[("ws-b", "a")].input_cost_per_token == Decimal("0")


@pytest.mark.asyncio
async def test_a_name_listed_twice_is_written_once(engine):
    written = await _upsert(engine, [_row("a", price="0.000001"), _row("a", price="0.000003")])

    rows = await _rows(engine)
    assert list(written) == ["a"]
    assert rows[(WORKSPACE, "a")].input_cost_per_token == Decimal("0.000003")


@pytest.mark.asyncio
async def test_the_statement_count_does_not_grow_with_the_model_list(engine):
    await _upsert(engine, [_row(f"old-{i}") for i in range(50)])
    statements: list[str] = []
    event.listen(
        engine.sync_engine,
        "before_cursor_execute",
        lambda _conn, _cursor, statement, *_: statements.append(statement),
    )

    await _upsert(
        engine, [_row(f"old-{i}") for i in range(50)] + [_row(f"new-{i}") for i in range(50)]
    )

    assert 1 <= len(statements) <= 3, statements
    assert len(await _rows(engine)) == 100
