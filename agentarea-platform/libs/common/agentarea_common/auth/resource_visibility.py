"""What the authorization graph says a user may read.

``require_permission`` answers that one object at a time, which is what a detail
endpoint needs. A list endpoint needs the other direction -- every object the
caller may read -- because filtering a page after the fact breaks its counts,
and fetching the page first and checking each row costs one graph round trip per
row.

Neither helper has a fallback. An unreachable graph raises, exactly as a write
grant does: answering "everything" because the PDP is down is how an outage
turns into an exposure, and answering "nothing" would look like data loss.
"""

from __future__ import annotations

from ..rebac.openfga_client import OpenFGAClient
from ..rebac.ownership import ResourceOwnershipError, resolve_graph_client


class ResourceVisibilityError(RuntimeError):
    """The graph could not say what this user may read."""


async def readable_resource_ids(user_id: str) -> set[str]:
    """Ids of ``resource:`` objects the user may read.

    Includes everything reachable through the workspace root project, which is
    how a plain member sees their workspace (see
    ``workspaces.memberships.workspace_baseline_role``), and anything granted to
    them directly.
    """
    try:
        resolved = resolve_graph_client()
    except ResourceOwnershipError as exc:
        raise ResourceVisibilityError(str(exc)) from exc
    if resolved is None:
        raise ResourceVisibilityError("no access-control backend is configured")
    client, backend = resolved
    if not isinstance(client, OpenFGAClient):
        raise ResourceVisibilityError(
            f"{backend} cannot enumerate readable resources; list filtering needs OpenFGA"
        )
    return set(
        await client.list_objects(
            namespace="resource",
            relation="can_read",
            subject_id=f"User:{user_id}",
        )
    )
