"""The counts the daily pulse sends, read across every workspace of the installation.

The tables belong to other libraries, which this one cannot import, so they are
named here by the columns the pulse reads. Only counts and enum-like values leave:
a resource from AgentArea's own catalog is its catalog slug, anything else,
including an item of a registry the operator added, is ``custom``. The platform
workspace, which holds what the operator supplies, is no tenant's and is not
counted.
"""

from collections import Counter
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    String,
    TableClause,
    case,
    cast,
    column,
    exists,
    func,
    literal,
    or_,
    select,
    table,
    union,
)
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql import ColumnElement, FromClause

from ..constants import PLATFORM_WORKSPACE_ID
from .counters import enum_label

#: Fixed, arbitrary key for pg_try_advisory_xact_lock: one replica sends the pulse.
PULSE_LOCK_KEY = 4_107_726_903_118

#: Where AgentArea's own catalog comes from: the bucket every install reconciles
#: (chart, compose, data/registry-sources.yaml), and the registries migrations
#: created for the formerly built-in content. No other source's ids are sent.
OFFICIAL_CATALOG_SOURCES = (
    "https://agentarea-mcp-registry.s3.amazonaws.com/registry/",
    "builtin://",
)


def _scoped(name: str, *columns: Any) -> TableClause:
    return table(name, column("workspace_id", String), *columns)


_workspaces = table(
    "workspaces",
    column("id", String),
    column("owner_user_id", String),
    column("created_at", DateTime),
)
_memberships = _scoped("workspace_memberships", column("user_id", String))
_tasks = _scoped(
    "tasks",
    column("created_by", String),
    column("status", String),
    column("origin_type", String),
    column("result", JSON),
    column("created_at", DateTime),
    column("started_at", DateTime),
    column("completed_at", DateTime),
)
_agents = _scoped("agents", column("created_at", DateTime))
_mcp_instances = _scoped(
    "mcp_server_instances",
    column("server_spec_id", String),
    column("auth_config_id"),
    column("verification", JSON),
)
_mcp_specs = table("mcp_servers", column("id"), column("registry_item_id"))
_openapi = _scoped("openapi_connections", column("registry_item_id"), column("auth_config_id"))
_auth_configs = table("mcp_auth_configs", column("id"), column("auth_type", String))
_items = table(
    "registry_items",
    column("id"),
    column("external_id", String),
    column("name", String),
    column("registry_type", String),
    column("registry_id"),
)
_registries = table("registries", column("id"), column("source_url", String))
_official = or_(
    *(
        _registries.c.source_url.startswith(source, autoescape=True)
        for source in OFFICIAL_CATALOG_SOURCES
    )
)
_triggers = _scoped("triggers", column("trigger_type", String), column("is_active", Boolean))
_skills = _scoped("skills", column("registry_item_id"))
_bundles = _scoped("installed_bundles", column("name", String))
_policies = _scoped("policies")
_clients = _scoped("clients", column("kind", String))
_provider_configs = _scoped("provider_configs", column("provider_spec_id"))
_provider_specs = table("provider_specs", column("id"), column("provider_type", String))


def _tenant(rows: TableClause) -> ColumnElement[bool]:
    return rows.c.workspace_id != PLATFORM_WORKSPACE_ID


async def try_pulse_lock(session: AsyncSession) -> bool:
    """Whether this transaction holds the pulse lock; it is released when the transaction ends."""
    return bool(
        (await session.execute(select(func.pg_try_advisory_xact_lock(PULSE_LOCK_KEY)))).scalar_one()
    )


async def collect_pulse(session: AsyncSession, now: datetime) -> dict[str, Any]:
    """Every aggregate of the pulse but the installation's own, as of ``now``.

    A workspace or user is active in a window when it created a run in it.
    """
    day, week, month = now - timedelta(days=1), now - timedelta(days=7), now - timedelta(days=30)
    catalog_slug = case(
        (_official, func.coalesce(func.nullif(_items.c.external_id, ""), _items.c.name)),
        else_=literal("custom"),
    )
    auth_type = func.coalesce(_auth_configs.c.auth_type, "none")
    runs_24h = (_tenant(_tasks), _tasks.c.created_at >= day)

    mcp_from = (
        _mcp_instances.outerjoin(
            _mcp_specs, cast(_mcp_specs.c.id, String) == _mcp_instances.c.server_spec_id
        )
        .outerjoin(_items, _items.c.id == _mcp_specs.c.registry_item_id)
        .outerjoin(_registries, _registries.c.id == _items.c.registry_id)
        .outerjoin(_auth_configs, _auth_configs.c.id == _mcp_instances.c.auth_config_id)
    )
    openapi_from = (
        _openapi.outerjoin(_items, _items.c.id == _openapi.c.registry_item_id)
        .outerjoin(_registries, _registries.c.id == _items.c.registry_id)
        .outerjoin(_auth_configs, _auth_configs.c.id == _openapi.c.auth_config_id)
    )
    catalog_bundle = exists().where(
        _registries.c.id == _items.c.registry_id,
        _official,
        _items.c.registry_type == "bundles",
        _items.c.external_id == _bundles.c.name,
    )

    return {
        "workspaces": {
            "total": await _count(session, _workspaces, _workspaces.c.id != PLATFORM_WORKSPACE_ID),
            "active_7d": await _active(session, _tasks.c.workspace_id, week),
            "active_30d": await _active(session, _tasks.c.workspace_id, month),
        },
        "users": {
            "total": await _count(session, _users()),
            "active_7d": await _active(session, _tasks.c.created_by, week),
            "active_30d": await _active(session, _tasks.c.created_by, month),
        },
        "agents": {
            "total": await _count(session, _agents, _tenant(_agents)),
            "created_24h": await _count(
                session, _agents, _tenant(_agents), _agents.c.created_at >= day
            ),
        },
        "runs_24h": {
            "by_status": await _grouped(session, _tasks.c.status, _tasks, *runs_24h),
            "by_origin": await _grouped(
                session, func.coalesce(_tasks.c.origin_type, "unknown"), _tasks, *runs_24h
            ),
            "failed_by_reason": await _grouped(
                session,
                func.coalesce(_tasks.c.result["failure_reason"].as_string(), "unknown"),
                _tasks,
                *runs_24h,
                _tasks.c.status == "failed",
            ),
            "median_duration_seconds": await _median_duration(session, day),
        },
        "connectors": {
            "by_kind": {
                "mcp": await _count(session, _mcp_instances, _tenant(_mcp_instances)),
                "openapi": await _count(session, _openapi, _tenant(_openapi)),
            },
            "by_catalog": _summed(
                await _grouped(
                    session, catalog_slug, mcp_from, _tenant(_mcp_instances), label=False
                ),
                await _grouped(session, catalog_slug, openapi_from, _tenant(_openapi), label=False),
            ),
            "by_auth_type": _summed(
                await _grouped(session, auth_type, mcp_from, _tenant(_mcp_instances)),
                await _grouped(session, auth_type, openapi_from, _tenant(_openapi)),
            ),
            "by_verification_status": await _grouped(
                session,
                func.coalesce(_mcp_instances.c.verification["status"].as_string(), "unknown"),
                _mcp_instances,
                _tenant(_mcp_instances),
            ),
        },
        "triggers_active": await _grouped(
            session,
            _triggers.c.trigger_type,
            _triggers,
            _tenant(_triggers),
            _triggers.c.is_active.is_(True),
        ),
        "skills": await _grouped(
            session,
            catalog_slug,
            _skills.outerjoin(_items, _items.c.id == _skills.c.registry_item_id).outerjoin(
                _registries, _registries.c.id == _items.c.registry_id
            ),
            _tenant(_skills),
            label=False,
        ),
        "bundles": await _grouped(
            session,
            case((catalog_bundle, _bundles.c.name), else_=literal("custom")),
            _bundles,
            _tenant(_bundles),
            label=False,
        ),
        "policies": await _count(session, _policies, _tenant(_policies)),
        "clients": await _grouped(session, _clients.c.kind, _clients, _tenant(_clients)),
        "llm_providers": await _grouped(
            session,
            _provider_specs.c.provider_type,
            _provider_configs.join(
                _provider_specs, _provider_specs.c.id == _provider_configs.c.provider_spec_id
            ),
            _tenant(_provider_configs),
        ),
        "workspace_sizes": await _workspace_sizes(session),
        "activation_7d": await _activation(session, week),
    }


def _users() -> FromClause:
    return union(
        select(_memberships.c.user_id.label("user_id")).where(_tenant(_memberships)),
        select(_workspaces.c.owner_user_id.label("user_id")).where(
            _workspaces.c.id != PLATFORM_WORKSPACE_ID
        ),
    ).subquery()


async def _active(session: AsyncSession, who: ColumnElement[Any], since: datetime) -> int:
    statement = (
        select(func.count(who.distinct()))
        .select_from(_tasks)
        .where(_tenant(_tasks), _tasks.c.created_at >= since)
    )
    return int((await session.execute(statement)).scalar_one())


async def _median_duration(session: AsyncSession, since: datetime) -> float | None:
    seconds = func.extract("epoch", _tasks.c.completed_at - _tasks.c.started_at)
    median = (
        await session.execute(
            select(func.percentile_cont(0.5).within_group(seconds)).where(
                _tenant(_tasks), _tasks.c.completed_at >= since, _tasks.c.started_at.is_not(None)
            )
        )
    ).scalar_one()
    return None if median is None else round(float(median), 1)


async def _workspace_sizes(session: AsyncSession) -> dict[str, int]:
    members = (
        select(func.count(_memberships.c.user_id.distinct()).label("n"))
        .select_from(
            _workspaces.outerjoin(_memberships, _memberships.c.workspace_id == _workspaces.c.id)
        )
        .where(_workspaces.c.id != PLATFORM_WORKSPACE_ID)
        .group_by(_workspaces.c.id)
        .subquery()
    )
    bucket = case((members.c.n <= 1, "1"), (members.c.n <= 5, "2-5"), else_="6+")
    sizes = await _grouped(session, bucket, members, label=False)
    return {size: sizes.get(size, 0) for size in ("1", "2-5", "6+")}


async def _activation(session: AsyncSession, since: datetime) -> dict[str, int]:
    """Personal workspaces created since ``since``, and how many reached each milestone."""
    workspace = _workspaces.c

    def succeeded_within(days: int) -> ColumnElement[bool]:
        return exists().where(
            _tasks.c.workspace_id == workspace.id,
            _tasks.c.status == "completed",
            _tasks.c.completed_at <= workspace.created_at + timedelta(days=days),
        )

    row = (
        await session.execute(
            select(
                func.count(),
                func.count().filter(exists().where(_agents.c.workspace_id == workspace.id)),
                func.count().filter(succeeded_within(1)),
                func.count().filter(succeeded_within(7)),
            ).where(
                workspace.id == workspace.owner_user_id,
                workspace.id != PLATFORM_WORKSPACE_ID,
                workspace.created_at >= since,
            )
        )
    ).one()
    return {
        "personal_workspaces": row[0],
        "with_agent": row[1],
        "succeeded_within_1d": row[2],
        "succeeded_within_7d": row[3],
    }


async def _count(session: AsyncSession, from_: FromClause, *where: ColumnElement[bool]) -> int:
    statement = select(func.count()).select_from(from_).where(*where)
    return int((await session.execute(statement)).scalar_one())


async def _grouped(
    session: AsyncSession,
    key: ColumnElement[Any],
    from_: FromClause,
    *where: ColumnElement[bool],
    label: bool = True,
) -> dict[str, int]:
    """Row counts by ``key``; with ``label``, a key that is not enum-like is counted as ``other``."""
    rows = await session.execute(
        select(key, func.count()).select_from(from_).where(*where).group_by(key)
    )
    counts: Counter[str] = Counter()
    for value, n in rows.all():
        counts[enum_label(str(value)) if label else str(value)] += n
    return dict(counts)


def _summed(*parts: dict[str, int]) -> dict[str, int]:
    total: Counter[str] = Counter()
    for part in parts:
        total.update(part)
    return dict(total)
