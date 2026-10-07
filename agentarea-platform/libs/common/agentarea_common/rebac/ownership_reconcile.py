"""Write the ownership tuples of governed rows that reached the database without them.

``WorkspaceScopedRepository.create`` grants ownership for every row it creates,
but rows written by SQL -- a data migration's backfill, a restore, a row created
before the grant moved into the repository -- have none, and the graph then
refuses them to everyone, their creator included. This walks every governed
table and grants the rows the graph has never seen, plus each member's baseline
role. Only ever adds; idempotent. The workspace-admin projection has one writer
(the workspace seed); the reconcile script repairs it on request.

Run by hand through ``scripts/20260923_reconcile_resource_authz.py``.
"""

from __future__ import annotations

import importlib
import importlib.util
import logging
import pkgutil
import re
from collections.abc import Iterable
from pathlib import Path
from typing import Any, Protocol

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.workspaces.models import Workspace

from .models import RelationQuery, RelationTuple
from .ownership import OWNER_RELATIONS, graph_governed_models, root_project_id

logger = logging.getLogger(__name__)

_GOVERNED_DECLARATION = re.compile(r"^\s+__graph_resource__\s*=\s*True\b", re.MULTILINE)


class TupleGraph(Protocol):
    async def write_tuple(self, tuple_: RelationTuple) -> None: ...

    async def delete_tuple(self, tuple_: RelationTuple) -> None: ...

    async def query_all_tuples(self, query: RelationQuery) -> list[RelationTuple]: ...


def load_governed_models() -> list[type]:
    """Import every module that declares a governed model, then read the registry.

    ``graph_governed_models()`` sees only mapped models, and a model is mapped
    only once its module is imported. Importing a hand-kept list left new
    governed models unmapped here and their rows unrepaired, so the modules are
    found by the declaration itself across every installed ``agentarea_*``
    package.
    """
    for package in pkgutil.iter_modules():
        if not package.ispkg or not package.name.startswith("agentarea_"):
            continue
        spec = importlib.util.find_spec(package.name)
        if spec is None or spec.submodule_search_locations is None:
            raise RuntimeError(f"package {package.name} was listed but cannot be located")
        for location in spec.submodule_search_locations:
            root = Path(location)
            for path in sorted(root.rglob("*.py")):
                if not _GOVERNED_DECLARATION.search(path.read_text(encoding="utf-8")):
                    continue
                parts = [package.name, *path.relative_to(root).with_suffix("").parts]
                if parts[-1] == "__init__":
                    parts.pop()
                importlib.import_module(".".join(parts))
    return graph_governed_models()


class TupleWriter:
    """Writes tuples the graph lacks; ``present`` is a snapshot of what it already holds.

    With a snapshot, a tuple already in it costs nothing, so a run over a graph
    that is already whole is one paged read instead of a write per tuple.
    """

    def __init__(
        self, client: TupleGraph, dry_run: bool, present: Iterable[RelationTuple] = ()
    ) -> None:
        self._client = client
        self._dry_run = dry_run
        self._present = {str(t) for t in present}
        self.written = 0
        self.deleted = 0

    async def ensure(self, relationship: RelationTuple) -> None:
        key = str(relationship)
        if key in self._present:
            return
        if self._dry_run:
            logger.info("would write %s", relationship)
            self.written += 1
            self._present.add(key)
            return
        try:
            await self._client.write_tuple(relationship)
            self.written += 1
        except Exception as exc:
            message = str(exc).lower()
            if "already exists" in message or "tuple to be written already existed" in message:
                self._present.add(key)
                return
            logger.exception("write failed for %s", relationship)
            raise
        self._present.add(key)

    async def remove(self, relationship: RelationTuple) -> None:
        if self._dry_run:
            logger.info("would delete %s", relationship)
        else:
            await self._client.delete_tuple(relationship)
        self._present.discard(str(relationship))
        self.deleted += 1


async def reconcile_resources(
    writer: TupleWriter, rows: Iterable[Any], workspace_owners: dict[str, str]
) -> None:
    for row in rows:
        resource_id = str(row.id)
        workspace_id = str(row.workspace_id)
        # `created_by` is the person who actually made it; the workspace owner is
        # the fallback for rows old enough to predate the column being filled.
        owner = str(row.created_by or "") or workspace_owners.get(workspace_id, "")
        if not owner:
            logger.warning("resource %s has no owner to grant; skipped", resource_id)
            continue
        await writer.ensure(
            RelationTuple(
                namespace="resource",
                object=resource_id,
                relation="project",
                subject_id=f"project:{root_project_id(workspace_id)}",
            )
        )
        for relation in OWNER_RELATIONS:
            await writer.ensure(
                RelationTuple(
                    namespace="resource",
                    object=resource_id,
                    relation=relation,
                    subject_id=f"User:{owner}",
                )
            )


async def reconcile_member_roles(writer: TupleWriter, client: TupleGraph) -> int:
    memberships = await client.query_all_tuples(
        RelationQuery(namespace="Workspace", relation="members")
    )
    seen = 0
    for membership in memberships:
        if not membership.subject_id or not membership.subject_id.startswith("User:"):
            continue
        seen += 1
        await writer.ensure(
            RelationTuple(
                namespace="project",
                object=root_project_id(membership.object),
                relation="reader",
                subject_id=membership.subject_id,
            )
        )
    return seen


async def load_workspace_owners(session: AsyncSession) -> dict[str, str]:
    rows = (await session.execute(select(Workspace.id, Workspace.owner_user_id))).all()
    return {str(row.id): str(row.owner_user_id) for row in rows}


async def reconcile_resource_ownership(
    session: AsyncSession,
    writer: TupleWriter,
    workspace_owners: dict[str, str],
) -> int:
    """Grant governed rows their owner and root project; return rows walked."""
    models: list[Any] = load_governed_models()
    logger.info("governed tables: %s", ", ".join(m.__tablename__ for m in models))
    walked = 0
    with unscoped("reconcile walks every governed row of every workspace"):
        for model in models:
            rows = (
                await session.execute(select(model.id, model.workspace_id, model.created_by))
            ).all()
            await reconcile_resources(writer, rows, workspace_owners)
            walked += len(rows)
            logger.info("reconciled %d %s rows", len(rows), model.__tablename__)
    return walked
