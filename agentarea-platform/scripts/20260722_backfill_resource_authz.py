"""Backfill the resource/project authorization model onto existing data.

Idempotent. Run inside the API container so it inherits DB + OpenFGA env:

    docker compose -f docker-compose.dev.yaml exec app \
        uv run python scripts/20260722_backfill_resource_authz.py

For every existing workspace it seeds the graph the way ``seed_workspace`` does
(creator/owner as ``admin``, ``members``, and a default ``project:<ws>-root``).
For every existing agent, skill, MCP server, and client it mirrors the legacy
PascalCase ownership grant onto ``resource:<id>`` (attaching it to the workspace
root project and granting each owner reader/writer/manager). Ownership is never
lost: an entity with no legacy owner tuple falls back to its workspace owner as
manager.
"""

from __future__ import annotations

import asyncio
import logging

from agentarea_common.config import get_database, get_settings
from agentarea_common.rebac.models import RelationQuery, RelationTuple
from agentarea_common.rebac.openfga_bootstrap import bootstrap_openfga
from agentarea_common.rebac.openfga_client import OpenFGAClient
from sqlalchemy import text

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("backfill_resource_authz")


def _root_project_id(workspace_id: str) -> str:
    return f"{workspace_id}-root"


async def _write(client: OpenFGAClient, relationship: RelationTuple) -> bool:
    try:
        await client.write_tuple(relationship)
        return True
    except Exception as exc:
        message = str(exc).lower()
        if "already exists" in message or "tuple to be written already existed" in message:
            return False
        logger.exception("write failed for %s", relationship)
        raise


async def _seed_workspace(client: OpenFGAClient, workspace_id: str, owner_user_id: str) -> int:
    written = 0
    written += await _write(
        client,
        RelationTuple(
            namespace="Workspace",
            object=workspace_id,
            relation="members",
            subject_id=f"User:{owner_user_id}",
        ),
    )
    written += await _write(
        client,
        RelationTuple(
            namespace="Workspace",
            object=workspace_id,
            relation="admin",
            subject_id=f"User:{owner_user_id}",
        ),
    )
    written += await _write(
        client,
        RelationTuple(
            namespace="project",
            object=_root_project_id(workspace_id),
            relation="workspace",
            subject_id=f"Workspace:{workspace_id}",
        ),
    )
    return written


# (DB table, legacy PascalCase namespace, legacy ownership relation).
_ENTITY_SOURCES = (
    ("agents", "Agent", "owners"),
    ("skills", "Skill", "owners"),
    ("mcp_servers", "MCPServer", "operators"),
    ("clients", "Client", "owners"),
)


async def _migrate_resource(
    client: OpenFGAClient,
    resource_id: str,
    workspace_id: str,
    workspace_owner: str,
    legacy_namespace: str,
    legacy_relation: str,
) -> int:
    owners = await client.query_all_tuples(
        RelationQuery(namespace=legacy_namespace, object=resource_id, relation=legacy_relation)
    )
    owner_subjects = sorted(
        {t.subject_id for t in owners if t.subject_id and t.subject_id.startswith("User:")}
    )
    if not owner_subjects and workspace_owner:
        owner_subjects = [f"User:{workspace_owner}"]

    written = 0
    written += await _write(
        client,
        RelationTuple(
            namespace="resource",
            object=resource_id,
            relation="project",
            subject_id=f"project:{_root_project_id(workspace_id)}",
        ),
    )
    for subject in owner_subjects:
        for relation in ("reader", "writer", "manager"):
            written += await _write(
                client,
                RelationTuple(
                    namespace="resource",
                    object=resource_id,
                    relation=relation,
                    subject_id=subject,
                ),
            )
    return written


async def main() -> None:
    settings = get_settings()
    if settings.access_control.ACCESS_CONTROL_BACKEND != "openfga":
        raise SystemExit(
            f"ACCESS_CONTROL_BACKEND={settings.access_control.ACCESS_CONTROL_BACKEND!r}; "
            "this backfill targets OpenFGA."
        )

    await bootstrap_openfga(settings.openfga)
    client = OpenFGAClient(
        api_url=settings.openfga.ACCESS_CONTROL_OPENFGA_API_URL,
        store_id=settings.openfga.ACCESS_CONTROL_OPENFGA_STORE_ID,
        authorization_model_id=settings.openfga.ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID,
        timeout_seconds=settings.openfga.ACCESS_CONTROL_OPENFGA_TIMEOUT_SECONDS,
    )

    database = get_database()
    ws_written = 0
    resource_written = 0
    resource_count = 0
    try:
        async with database.async_session_factory() as session:
            workspaces = (
                await session.execute(text("SELECT id, owner_user_id FROM workspaces"))
            ).all()
            rows_by_table = {}
            for table, _namespace, _relation in _ENTITY_SOURCES:
                rows_by_table[table] = (
                    await session.execute(text(f"SELECT id, workspace_id FROM {table}"))  # noqa: S608
                ).all()

        owner_by_workspace = {str(w.id): str(w.owner_user_id) for w in workspaces}
        for workspace_id, owner_user_id in owner_by_workspace.items():
            ws_written += await _seed_workspace(client, workspace_id, owner_user_id)
        logger.info("seeded %d workspaces (%d tuples written)", len(owner_by_workspace), ws_written)

        for table, namespace, relation in _ENTITY_SOURCES:
            rows = rows_by_table[table]
            for row in rows:
                resource_id = str(row.id)
                workspace_id = str(row.workspace_id)
                workspace_owner = owner_by_workspace.get(workspace_id, "")
                if not workspace_owner:
                    logger.warning(
                        "%s %s references unknown workspace %s; owner fallback skipped",
                        namespace,
                        resource_id,
                        workspace_id,
                    )
                resource_written += await _migrate_resource(
                    client, resource_id, workspace_id, workspace_owner, namespace, relation
                )
            resource_count += len(rows)
            logger.info("migrated %d %s rows", len(rows), table)
    finally:
        await client.aclose()

    logger.info(
        "backfill complete: %d workspace tuples, %d resource tuples across %d entities",
        ws_written,
        resource_written,
        resource_count,
    )


if __name__ == "__main__":
    asyncio.run(main())
