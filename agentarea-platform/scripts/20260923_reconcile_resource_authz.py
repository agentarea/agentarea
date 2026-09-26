"""Repair ownership tuples for rows that reached the database without them.

Idempotent; safe to re-run. Run inside the API container so it inherits DB +
OpenFGA env:

    docker compose -f docker-compose.dev.yaml exec app \
        uv run python scripts/20260923_reconcile_resource_authz.py [--dry-run]

Two things go missing, and both leave the graph saying "no" about rows that are
plainly visible in the product:

1. **Resources created outside the HTTP routes.** Until 2026-09-23 the ownership
   grant lived at the route, so ``agentarea/agents.create`` and the three
   skill-creating tool methods in ``libs/agents`` wrote none. Those rows fail
   closed in ``OpenFGAPermissionService``: their own creator gets 403 on edit
   and delete. New rows are covered by ``WorkspaceScopedRepository.create``;
   this repairs the ones already written.

2. **The member baseline role.** ``Workspace#members`` grants nothing by itself
   -- the root project has no branch for a member -- so membership now also
   writes ``project:<ws>-root#reader``. Members who joined before that have the
   membership tuple and no role.

With ``--revoke-ended-memberships`` it also goes the other way, and deletes:

3. **Grants an ended membership left behind.** Removal ends the membership row
   first and the graph second; until the graph step was queued in the outbox, a
   failed graph call left ``Workspace#members`` and the root ``reader`` role in
   place. Those tuples are dropped for every user with no membership row who does
   not own the workspace. Members admitted before membership rows were written
   have no row either, which is why this runs only when asked for: check the
   ``--dry-run`` output first.

Which tables to walk is read off the models themselves (``__graph_resource__``):
every installed ``agentarea_*`` module declaring one is imported, so this stays
in step with the runtime instead of repeating a list that rots.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib.util
import logging
import pkgutil
import re
from collections.abc import Awaitable, Callable
from pathlib import Path

from agentarea_common.config import get_database, get_settings
from agentarea_common.rebac.models import RelationQuery, RelationTuple
from agentarea_common.rebac.openfga_bootstrap import bootstrap_openfga
from agentarea_common.rebac.openfga_client import OpenFGAClient
from agentarea_common.rebac.ownership import (
    OWNER_RELATIONS,
    graph_governed_models,
    root_project_id,
)
from sqlalchemy import select, text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("reconcile_resource_authz")

_GOVERNED_DECLARATION = re.compile(r"^\s+__graph_resource__\s*=\s*True\b", re.MULTILINE)


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


class _Writer:
    def __init__(self, client: OpenFGAClient, dry_run: bool) -> None:
        self._client = client
        self._dry_run = dry_run
        self.written = 0
        self.deleted = 0

    async def ensure(self, relationship: RelationTuple) -> None:
        if self._dry_run:
            logger.info("would write %s", relationship)
            self.written += 1
            return
        try:
            await self._client.write_tuple(relationship)
            self.written += 1
        except Exception as exc:
            message = str(exc).lower()
            if "already exists" in message or "tuple to be written already existed" in message:
                return
            logger.exception("write failed for %s", relationship)
            raise

    async def remove(self, relationship: RelationTuple) -> None:
        if self._dry_run:
            logger.info("would delete %s", relationship)
        else:
            await self._client.delete_tuple(relationship)
        self.deleted += 1


async def _reconcile_resources(writer: _Writer, rows, workspace_owners: dict[str, str]) -> None:
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


async def _reconcile_workspace_admins(writer: _Writer, owners: dict[str, str]) -> None:
    """Project each workspace's owner onto ``Workspace#admin``.

    Two representations of one fact: ``workspaces.owner_user_id`` answers
    ``requires_workspace_admin()``, while ``Workspace#admin`` is what OpenFGA
    evaluates in ``project.can_read: ... or admin from workspace`` -- the branch
    that lets an admin reach objects they do not own. They agree by construction
    at creation time and nothing changes ownership afterwards, but a seed that
    failed halfway leaves an admin who can rewrite policy and cannot open an
    agent. The column is the authority; this writes the projection.
    """
    for workspace_id, owner in owners.items():
        if not owner:
            logger.warning("workspace %s has no owner_user_id; skipped", workspace_id)
            continue
        await writer.ensure(
            RelationTuple(
                namespace="Workspace",
                object=workspace_id,
                relation="admin",
                subject_id=f"User:{owner}",
            )
        )
        await writer.ensure(
            RelationTuple(
                namespace="project",
                object=root_project_id(workspace_id),
                relation="workspace",
                subject_id=f"Workspace:{workspace_id}",
            )
        )


async def _reconcile_member_roles(writer: _Writer, client: OpenFGAClient) -> int:
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


async def _revoke_ended_memberships(
    writer: _Writer,
    client: OpenFGAClient,
    *,
    load_members: Callable[[str], Awaitable[set[str]]],
    owners: dict[str, str],
) -> int:
    """Delete the member grants of every user whose membership has ended.

    ``load_members`` reads a workspace's membership rows. It is called per
    workspace right before that workspace's tuples are deleted, so a member
    admitted while the run is under way keeps their grants. A workspace with no
    row in ``owners`` is a personal one, owned by the user sharing its id.
    """
    root_suffix = root_project_id("")
    grants = await client.query_all_tuples(RelationQuery(namespace="Workspace", relation="members"))
    grants += [
        t
        for t in await client.query_all_tuples(
            RelationQuery(namespace="project", relation="reader")
        )
        if t.object.endswith(root_suffix)
    ]
    by_workspace: dict[str, list[tuple[str, RelationTuple]]] = {}
    for grant in grants:
        if not grant.subject_id or not grant.subject_id.startswith("User:"):
            continue
        user_id = grant.subject_id.removeprefix("User:")
        workspace_id = (
            grant.object.removesuffix(root_suffix) if grant.namespace == "project" else grant.object
        )
        if owners.get(workspace_id, workspace_id) == user_id:
            continue
        by_workspace.setdefault(workspace_id, []).append((user_id, grant))
    for workspace_id, candidates in by_workspace.items():
        members = await load_members(workspace_id)
        for user_id, grant in candidates:
            if user_id not in members:
                await writer.remove(grant)
    return writer.deleted


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--dry-run", action="store_true", help="report what would be written, write nothing"
    )
    parser.add_argument(
        "--revoke-ended-memberships",
        action="store_true",
        help="also delete member grants of users with no membership row (owners excepted)",
    )
    args = parser.parse_args()

    settings = get_settings()
    if settings.access_control.ACCESS_CONTROL_BACKEND != "openfga":
        raise SystemExit(
            f"ACCESS_CONTROL_BACKEND={settings.access_control.ACCESS_CONTROL_BACKEND!r}; "
            "this reconcile targets OpenFGA."
        )

    await bootstrap_openfga(settings.openfga)
    client = OpenFGAClient(
        api_url=settings.openfga.ACCESS_CONTROL_OPENFGA_API_URL,
        store_id=settings.openfga.ACCESS_CONTROL_OPENFGA_STORE_ID,
        authorization_model_id=settings.openfga.ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID,
        timeout_seconds=settings.openfga.ACCESS_CONTROL_OPENFGA_TIMEOUT_SECONDS,
    )
    writer = _Writer(client, args.dry_run)
    models = load_governed_models()
    logger.info("governed tables: %s", ", ".join(m.__tablename__ for m in models))

    database = get_database()
    resource_count = 0
    try:
        async with database.async_session_factory() as session:
            workspace_owners = {
                str(row.id): str(row.owner_user_id)
                for row in (
                    await session.execute(text("SELECT id, owner_user_id FROM workspaces"))
                ).all()
            }
            for model in models:
                rows = (
                    await session.execute(select(model.id, model.workspace_id, model.created_by))
                ).all()
                await _reconcile_resources(writer, rows, workspace_owners)
                resource_count += len(rows)
                logger.info("reconciled %d %s rows", len(rows), model.__tablename__)

        await _reconcile_workspace_admins(writer, workspace_owners)
        logger.info("reconciled admin projections for %d workspaces", len(workspace_owners))

        if args.revoke_ended_memberships:

            async def load_members(workspace_id: str) -> set[str]:
                async with database.async_session_factory() as session:
                    rows = await session.execute(
                        text(
                            "SELECT user_id FROM workspace_memberships "
                            "WHERE workspace_id = :workspace_id"
                        ),
                        {"workspace_id": workspace_id},
                    )
                    return {str(user_id) for user_id in rows.scalars()}

            revoked = await _revoke_ended_memberships(
                writer, client, load_members=load_members, owners=workspace_owners
            )
            logger.info(
                "%s %d grants of ended memberships",
                "would delete" if args.dry_run else "deleted",
                revoked,
            )

        members = await _reconcile_member_roles(writer, client)
        logger.info("reconciled baseline roles for %d workspace memberships", members)
    finally:
        await client.aclose()

    logger.info(
        "%s: %d tuples across %d resources",
        "would write" if args.dry_run else "wrote",
        writer.written,
        resource_count,
    )


if __name__ == "__main__":
    asyncio.run(main())
