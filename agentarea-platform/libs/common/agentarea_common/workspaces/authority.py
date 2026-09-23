"""Who may administer a workspace, resolved from ownership.

``UserContext.admin_workspaces`` used to be filled in exactly one place -- the
HTTP request dependency. Every other door that mints a context (the MCP bearer
path, the worker's code-tool activity, trigger channels) left it ``None``, so
``assert_workspace_admin`` denied there unconditionally and nobody noticed,
because no non-HTTP caller asked. The moment one does -- a platform toolset
gating a secret write the way its REST twin does -- the field has to mean the
same thing on both sides.

So ``None`` means "not resolved yet" and ``[]`` means "resolved, administers
nothing". The distinction is what lets a non-HTTP caller answer the question at
all without re-implementing it.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


async def administered_workspace_ids(user_id: str) -> list[str]:
    """Workspaces ``user_id`` owns, which is what confers administrative authority.

    A failed lookup returns an empty list: denying an admin action is
    recoverable, granting one on a failed lookup is not.
    """
    from agentarea_common.config.database import get_database
    from agentarea_common.workspaces.repository import WorkspaceRepository

    try:
        database = get_database()
        async with database.async_session_factory() as session:
            owned = await WorkspaceRepository(session).list_owned_by_user(user_id)
        return [workspace.id for workspace in owned]
    except Exception as exc:
        logger.warning(
            "Could not resolve owned workspaces for user %s: %s", user_id, exc, exc_info=True
        )
        return []
