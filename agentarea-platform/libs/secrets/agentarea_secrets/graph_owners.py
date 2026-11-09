"""Grant the owner of every user secret whose ownership has not reached the graph.

Using a secret is ``can_use_secret`` on ``resource:<secret id>``. A create grants
its creator and stamps ``graph_granted_at``; a secret made before secrets were
graph resources, or one whose create could not stamp it, is still null. The
reconcile grants each such secret its ``created_by`` and stamps it, so the pass
finds nothing left once it has run.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from agentarea_common.auth.context import Subject
from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.rebac.ownership import grant_resource_owner
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EncryptedSecret

logger = logging.getLogger(__name__)


async def grant_pending_secret_owners(session: AsyncSession) -> int:
    """Grant and stamp every user secret not yet in the graph; return how many."""
    with unscoped("user secrets of every workspace whose owner the graph does not have yet"):
        result = await session.execute(
            select(EncryptedSecret)
            .where(EncryptedSecret.owner_type.is_(None), EncryptedSecret.graph_granted_at.is_(None))
            .order_by(EncryptedSecret.workspace_id, EncryptedSecret.id)
        )
        pending = list(result.scalars().all())
        for secret in pending:
            await grant_resource_owner(
                resource_id=secret.id,
                workspace_id=secret.workspace_id,
                owner=Subject(kind="user", id=secret.created_by).graph_subject,
            )
            secret.graph_granted_at = datetime.now(UTC)
            await session.commit()
    if pending:
        logger.info("Granted the owners of %d user secrets", len(pending))
    return len(pending)
