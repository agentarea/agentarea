"""Resolve the display name of whatever owns a managed secret.

The catalog cannot do this itself. It sits underneath every library that stores
a credential — `agentarea_llm` already imports it — so reaching back into those
tables from there would invert the dependency. This app already depends on all
of them, which makes it the place, the same way access-control grants are
composed here rather than in the libraries they describe.

One query per owner type present in the page, not one per row.
"""

from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# owner_type -> the table holding it. Only types the catalog surfaces appear
# here; anything else is machine-generated and never reaches a page.
_OWNER_TABLES: dict[str, str] = {
    "provider_config": "provider_configs",
    "mcp_instance": "mcp_server_instances",
    "mcp_auth_config": "mcp_auth_configs",
    "openapi_connection": "openapi_connections",
    "trigger": "triggers",
    "agent": "agents",
}


async def resolve_owner_names(
    session: AsyncSession, workspace_id: str, owners: list[tuple[str, str]]
) -> dict[tuple[str, str], str]:
    """Map (owner_type, owner_id) to a display name, omitting owners that are gone.

    A missing entry is meaningful rather than an error: a secret can outlive the
    connection that minted it, and saying so is more useful than inventing a name.
    """
    by_type: dict[str, set[str]] = {}
    for owner_type, owner_id in owners:
        if owner_type in _OWNER_TABLES:
            by_type.setdefault(owner_type, set()).add(owner_id)

    resolved: dict[tuple[str, str], str] = {}
    for owner_type, ids in by_type.items():
        valid = [i for i in ids if _is_uuid(i)]
        if not valid:
            continue
        table = _OWNER_TABLES[owner_type]
        rows = await session.execute(
            text(
                f"SELECT id::text AS id, name FROM {table} "  # noqa: S608 - table from a fixed map
                "WHERE id = ANY(CAST(:ids AS uuid[])) AND workspace_id = :workspace_id"
            ),
            {"ids": valid, "workspace_id": workspace_id},
        )
        for row in rows:
            resolved[(owner_type, row.id)] = row.name
    return resolved


def _is_uuid(value: str) -> bool:
    try:
        UUID(value)
    except ValueError:
        return False
    return True
