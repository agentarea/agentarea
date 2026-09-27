"""No workspace-scoped row crosses the tenant boundary through the ORM.

Parametrized over every model that mixes in ``WorkspaceScopedMixin``, found by
scanning the source and cross-checked against the mapped classes, so a new
model is covered the day it lands. A row written in workspace A is invisible
from B through a select, a get by id, a relationship load, a bulk update and a
bulk delete; the models whose rows are readable beyond their workspace assert
exactly that visibility, and bulk writes stay strict for them too.

Runs on in-memory SQLite with the full metadata. With
``TENANT_SCOPE_TEST_DATABASE_URL`` set (``make check-db``) the same cases run
against the migrated Postgres schema as well.
"""

from __future__ import annotations

import ast
import importlib
import os
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from agentarea_common.base.models import BaseModel, WorkspaceScopedMixin
from agentarea_common.base.tenant_scope import tenant_scoped_session_class, workspace_scope
from agentarea_common.config.database import TenantScopeMode
from agentarea_common.constants import MANAGED_BY_PLATFORM, PLATFORM_WORKSPACE_ID
from agentarea_common.testing import sqlite_compat  # noqa: F401
from sqlalchemy import Column, Enum, Table, delete, insert, inspect, select, text, update
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import RelationshipProperty, selectinload
from sqlalchemy.pool import StaticPool

PLATFORM_ROOT = Path(__file__).resolve().parents[2]
EXPECTED_MODEL_COUNT = 25

WS_A = "tenant-scope-a"
WS_B = "tenant-scope-b"
PG_URL = os.getenv("TENANT_SCOPE_TEST_DATABASE_URL", "")


def _declared_models() -> dict[str, str]:
    """``{class name: module}`` for every production class deriving from the mixin."""
    declared: dict[str, str] = {}
    for root in ("libs", "apps"):
        for path in (PLATFORM_ROOT / root).glob("*/agentarea_*/**/*.py"):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if not isinstance(node, ast.ClassDef):
                    continue
                bases = {getattr(b, "id", None) or getattr(b, "attr", None) for b in node.bases}
                if "WorkspaceScopedMixin" in bases:
                    package_root = path.parents[len(path.relative_to(PLATFORM_ROOT).parts) - 3]
                    module = ".".join(path.relative_to(package_root).with_suffix("").parts)
                    declared[node.name] = module
    return declared


def _scoped_models() -> list[type]:
    declared = _declared_models()
    for module in set(declared.values()):
        importlib.import_module(module)
    importlib.import_module("agentarea_registry.domain.models")
    found: dict[str, type] = {}
    pending = list(WorkspaceScopedMixin.__subclasses__())
    while pending:
        cls = pending.pop()
        pending.extend(cls.__subclasses__())
        mapper = inspect(cls, raiseerr=False)
        if mapper is not None and cls.__module__ == declared.get(cls.__name__):
            found[cls.__name__] = cls
    assert set(found) == set(declared), (
        f"declared but not mapped: {sorted(set(declared) - set(found))}"
    )
    return sorted(found.values(), key=lambda cls: cls.__name__)


MODELS = _scoped_models()


def _scoped_relationships() -> list[tuple[type, RelationshipProperty]]:
    pairs = []
    seen: set[tuple[type, str]] = set()
    for model in MODELS:
        for other in inspect(model).mapper.registry.mappers:
            for rel in other.relationships:
                if rel.mapper.class_ is model and (other.class_, rel.key) not in seen:
                    seen.add((other.class_, rel.key))
                    pairs.append((other.class_, rel))
    return sorted(pairs, key=lambda p: f"{p[0].__name__}.{p[1].key}")


RELATIONSHIPS = _scoped_relationships()

# Readable from every workspace, and why (see each model's workspace_visibility).
READ_BY_EVERY_WORKSPACE = {"ProviderSpec"}


def test_every_scoped_model_is_covered() -> None:
    """A new scoped model is picked up here; bump the count after deciding its visibility."""
    assert len(MODELS) == EXPECTED_MODEL_COUNT, sorted(m.__name__ for m in MODELS)
    assert len(RELATIONSHIPS) > 10


def _value(column: Column, unique: str) -> Any:
    column_type = column.type
    if isinstance(column_type, Enum) and column_type.enums:
        return column_type.enums[0]
    try:
        python_type = column_type.python_type
    except NotImplementedError:
        return unique
    samples: dict[type, Any] = {
        str: unique,
        int: 0,
        bool: False,
        float: 0.0,
        Decimal: Decimal(0),
        dict: {},
        list: [],
        datetime: datetime.now(UTC).replace(tzinfo=None),
        date: date.today(),
        uuid.UUID: uuid.uuid4(),
        bytes: b"x",
    }
    for kind, sample in samples.items():
        if issubclass(python_type, kind):
            return sample
    return unique


def _row(table: Table, **given: Any) -> dict[str, Any]:
    row = dict(given)
    for column in table.columns:
        if column.name in row:
            continue
        if column.primary_key and column.name == "id":
            row["id"] = uuid.uuid4()
        elif not column.nullable and column.default is None and column.server_default is None:
            row[column.name] = _value(column, uuid.uuid4().hex[:8])
    return row


@dataclass
class Backend:
    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]
    written: list[tuple[Table, Any]]

    async def write(self, table: Table, **given: Any) -> dict[str, Any]:
        row = _row(table, **given)
        async with self.engine.begin() as conn:
            if conn.dialect.name == "sqlite":
                await conn.execute(text("PRAGMA foreign_keys=OFF"))
            else:
                await conn.execute(text("SET session_replication_role = replica"))
            await conn.execute(insert(table).values(**row))
        self.written.append((table, row))
        return row

    async def cleanup(self) -> None:
        async with self.engine.begin() as conn:
            if conn.dialect.name != "sqlite":
                await conn.execute(text("SET session_replication_role = replica"))
            for table, row in reversed(self.written):
                keys = [c for c in table.primary_key.columns]
                await conn.execute(
                    delete(table).where(*(c == row[c.name] for c in keys))
                )


def _backends() -> list[str]:
    return ["sqlite", *(["postgres"] if PG_URL else [])]


@pytest.fixture(params=_backends())
async def backend(request) -> AsyncIterator[Backend]:
    if request.param == "sqlite":
        engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.run_sync(BaseModel.metadata.create_all)
    else:
        engine = create_async_engine(PG_URL)
    sessions = async_sessionmaker(
        engine,
        sync_session_class=tenant_scoped_session_class(TenantScopeMode.ENFORCE),
        expire_on_commit=False,
    )
    state = Backend(engine=engine, sessions=sessions, written=[])
    try:
        yield state
    finally:
        await state.cleanup()
        await engine.dispose()


def _visible_from_b(model: type) -> bool:
    return model.__name__ in READ_BY_EVERY_WORKSPACE


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
async def test_select_stays_in_its_workspace(backend: Backend, model: type) -> None:
    row = await backend.write(model.__table__, workspace_id=WS_A, created_by="owner")

    async with backend.sessions() as session:
        with workspace_scope(WS_A):
            own = (await session.execute(select(model.id).where(model.id == row["id"]))).all()
        with workspace_scope(WS_B):
            foreign = (await session.execute(select(model).where(model.id == row["id"]))).all()

    assert len(own) == 1
    assert len(foreign) == (1 if _visible_from_b(model) else 0)


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
async def test_get_by_id_stays_in_its_workspace(backend: Backend, model: type) -> None:
    row = await backend.write(model.__table__, workspace_id=WS_A, created_by="owner")

    async with backend.sessions() as session:
        with workspace_scope(WS_B):
            found = await session.get(model, row["id"])

    assert (found is not None) == _visible_from_b(model)


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
async def test_bulk_update_stays_in_its_workspace(backend: Backend, model: type) -> None:
    row = await backend.write(model.__table__, workspace_id=WS_A, created_by="owner")

    async with backend.sessions() as session:
        with workspace_scope(WS_B):
            foreign = await session.execute(
                update(model).where(model.id == row["id"]).values(created_by="intruder")
            )
        with workspace_scope(WS_A):
            own = await session.execute(
                update(model).where(model.id == row["id"]).values(created_by="owner-2")
            )
        await session.rollback()

    assert foreign.rowcount == 0
    assert own.rowcount == 1


@pytest.mark.parametrize("model", MODELS, ids=lambda m: m.__name__)
async def test_bulk_delete_stays_in_its_workspace(backend: Backend, model: type) -> None:
    row = await backend.write(model.__table__, workspace_id=WS_A, created_by="owner")

    async with backend.sessions() as session:
        with workspace_scope(WS_B):
            foreign = await session.execute(delete(model).where(model.id == row["id"]))
        with workspace_scope(WS_A):
            own = await session.execute(delete(model).where(model.id == row["id"]))
        await session.rollback()

    assert foreign.rowcount == 0
    assert own.rowcount == 1


async def _link(backend: Backend, owner: type, rel: RelationshipProperty) -> tuple[Any, Any]:
    """A row of ``owner`` in B related through ``rel`` to a target row in A."""
    target_table = rel.mapper.local_table
    owner_row = _row(owner.__table__, workspace_id=WS_B, created_by="owner")
    target_row = _row(target_table, workspace_id=WS_A, created_by="owner")
    if rel.secondary is not None:
        link = {}
        for local, remote in rel.synchronize_pairs:
            link[remote.name] = owner_row[local.name]
        for local, remote in rel.secondary_synchronize_pairs:
            link[remote.name] = target_row[local.name]
        await backend.write(owner.__table__, **owner_row)
        await backend.write(target_table, **target_row)
        await backend.write(rel.secondary, **_row(rel.secondary, **link))
        return owner_row["id"], target_row["id"]
    for local, remote in rel.local_remote_pairs:
        if local.primary_key:
            target_row[remote.name] = owner_row[local.name]
        else:
            owner_row[local.name] = target_row[remote.name]
    await backend.write(owner.__table__, **owner_row)
    await backend.write(target_table, **target_row)
    return owner_row["id"], target_row["id"]


@pytest.mark.parametrize(
    "owner,rel", RELATIONSHIPS, ids=lambda v: getattr(v, "key", getattr(v, "__name__", ""))
)
async def test_relationship_load_stays_in_its_workspace(
    backend: Backend, owner: type, rel: RelationshipProperty
) -> None:
    owner_id, target_id = await _link(backend, owner, rel)
    target = rel.mapper.class_
    attribute = getattr(owner, rel.key)

    async with backend.sessions() as session:
        with workspace_scope(WS_B):
            loaded = (
                await session.execute(
                    select(owner).where(owner.id == owner_id).options(selectinload(attribute))
                )
            ).scalar_one()
            related = getattr(loaded, rel.key)

    ids = {item.id for item in related} if rel.uselist else ({related.id} if related else set())
    assert (target_id in ids) == _visible_from_b(target)


async def test_platform_rows_are_read_from_every_workspace(backend: Backend) -> None:
    from agentarea_llm.domain.models import ModelInstance, ModelSpec, ProviderConfig
    from agentarea_mcp.domain.models import MCPServer
    from agentarea_registry.domain.models import Registry, RegistryItem

    config = await backend.write(
        ProviderConfig.__table__,
        workspace_id=PLATFORM_WORKSPACE_ID,
        created_by="operator",
        managed_by=MANAGED_BY_PLATFORM,
    )
    tenant_config = await backend.write(
        ProviderConfig.__table__, workspace_id=WS_A, created_by="owner"
    )
    spec = await backend.write(
        ModelSpec.__table__, workspace_id=PLATFORM_WORKSPACE_ID, created_by="operator"
    )
    instance = await backend.write(
        ModelInstance.__table__,
        workspace_id=PLATFORM_WORKSPACE_ID,
        created_by="operator",
        provider_config_id=config["id"],
        model_spec_id=spec["id"],
    )
    tenant_instance = await backend.write(
        ModelInstance.__table__,
        workspace_id=WS_A,
        created_by="owner",
        provider_config_id=tenant_config["id"],
        model_spec_id=spec["id"],
    )
    active = await backend.write(Registry.__table__, is_active=True)
    inactive = await backend.write(Registry.__table__, is_active=False)
    active_item = await backend.write(RegistryItem.__table__, registry_id=active["id"])
    inactive_item = await backend.write(RegistryItem.__table__, registry_id=inactive["id"])
    mirror = await backend.write(
        MCPServer.__table__,
        workspace_id=PLATFORM_WORKSPACE_ID,
        created_by="reconcile",
        registry_item_id=active_item["id"],
    )
    stale_mirror = await backend.write(
        MCPServer.__table__,
        workspace_id=PLATFORM_WORKSPACE_ID,
        created_by="reconcile",
        registry_item_id=inactive_item["id"],
    )
    tenant_copy = await backend.write(
        MCPServer.__table__,
        workspace_id=WS_A,
        created_by="owner",
        registry_item_id=active_item["id"],
    )

    async def ids(session: AsyncSession, model: type) -> set[Any]:
        return set((await session.execute(select(model.id))).scalars())

    async with backend.sessions() as session:
        with workspace_scope(WS_B):
            assert config["id"] in await ids(session, ProviderConfig)
            assert tenant_config["id"] not in await ids(session, ProviderConfig)
            assert spec["id"] in await ids(session, ModelSpec)
            assert instance["id"] in await ids(session, ModelInstance)
            assert tenant_instance["id"] not in await ids(session, ModelInstance)
            assert mirror["id"] in await ids(session, MCPServer)
            assert stale_mirror["id"] not in await ids(session, MCPServer)
            assert tenant_copy["id"] not in await ids(session, MCPServer)

            refused = await session.execute(
                update(ProviderConfig)
                .where(ProviderConfig.id == config["id"])
                .values(name="repointed")
            )
            assert refused.rowcount == 0
        await session.rollback()


async def test_mcp_server_by_id_resolves_platform_mirrors_only(backend: Backend) -> None:
    from agentarea_common.auth.context import UserContext
    from agentarea_mcp.domain.models import MCPServer
    from agentarea_mcp.infrastructure.repository import MCPServerRepository
    from agentarea_registry.domain.models import Registry, RegistryItem

    registry = await backend.write(Registry.__table__, is_active=True)
    item = await backend.write(RegistryItem.__table__, registry_id=registry["id"])
    mirror = await backend.write(
        MCPServer.__table__,
        workspace_id=PLATFORM_WORKSPACE_ID,
        created_by="reconcile",
        registry_item_id=item["id"],
    )
    tenant_copy = await backend.write(
        MCPServer.__table__,
        workspace_id=WS_A,
        created_by="owner",
        registry_item_id=item["id"],
    )

    async with backend.sessions() as session:
        with workspace_scope(WS_B):
            repository = MCPServerRepository(
                session, UserContext(user_id="intruder", workspace_id=WS_B)
            )
            assert await repository.get_server_by_id(mirror["id"]) is not None
            assert await repository.get_server_by_id(tenant_copy["id"]) is None


async def test_auth_config_links_count_only_own_openapi_connections(backend: Backend) -> None:
    from agentarea_common.auth.context import UserContext
    from agentarea_mcp.infrastructure.auth_repository import MCPAuthConfigRepository
    from agentarea_openapi.domain.models import OpenAPIConnection

    config_id = uuid.uuid4()
    own = await backend.write(
        OpenAPIConnection.__table__, workspace_id=WS_B, created_by="owner", auth_config_id=config_id
    )
    await backend.write(
        OpenAPIConnection.__table__, workspace_id=WS_A, created_by="owner", auth_config_id=config_id
    )

    async with backend.sessions() as session:
        with workspace_scope(WS_B):
            repository = MCPAuthConfigRepository(
                session, UserContext(user_id="owner", workspace_id=WS_B)
            )
            linked = await repository.get_linked_openapi_connection_ids(config_id)

    assert linked == [str(own["id"])]
