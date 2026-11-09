"""Grant the owner of every user secret whose ownership has not reached the graph.

Using a secret is ``can_use_secret`` on ``resource:<secret id>``. A create grants
its creator and stamps ``graph_granted_at``; a secret made before secrets were
graph resources, or one whose create could not stamp it, is still null, and the
catalog authorizes it by the rule it was created under until this pass grants
its ``created_by`` and stamps it.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

from agentarea_common.auth.context import Subject
from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID
from agentarea_common.rebac.ownership import grant_resource_owner
from sqlalchemy import String, cast, column, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EncryptedSecret

logger = logging.getLogger(__name__)

# Read by id only; the agents library is not a dependency of this one.
_AGENTS = table("agents", column("id"))


@dataclass(frozen=True)
class SecretOwnerPass:
    granted: int
    skipped: int
    failed: int


async def grant_pending_secret_owners(session: AsyncSession) -> SecretOwnerPass:
    """Grant and stamp every user secret not yet in the graph.

    A secret an agent created is granted to that ``Agent``. One the platform
    principal created has no person to own it and is left unstamped, with a
    warning: until someone grants it, its workspace admins use it under the
    rule it was created with. A row the graph refuses is logged and counted;
    the pass goes on, and the caller fails once the rest is done.
    """
    granted = skipped = failed = 0
    with unscoped("user secrets of every workspace whose owner the graph does not have yet"):
        result = await session.execute(
            select(EncryptedSecret)
            .where(EncryptedSecret.owner_type.is_(None), EncryptedSecret.graph_granted_at.is_(None))
            .order_by(EncryptedSecret.workspace_id, EncryptedSecret.id)
        )
        pending = list(result.scalars().all())
        creators = {secret.created_by for secret in pending}
        agents = (
            set(
                (
                    await session.execute(
                        select(cast(_AGENTS.c.id, String)).where(
                            cast(_AGENTS.c.id, String).in_(creators)
                        )
                    )
                ).scalars()
            )
            if creators
            else set()
        )
        for secret in pending:
            if secret.created_by == PLATFORM_PRINCIPAL_ID:
                logger.warning(
                    "User secret %s in workspace %s was created by the platform principal; "
                    "no owner granted",
                    secret.id,
                    secret.workspace_id,
                )
                skipped += 1
                continue
            kind = "agent" if secret.created_by in agents else "user"
            try:
                await grant_resource_owner(
                    resource_id=secret.id,
                    workspace_id=secret.workspace_id,
                    owner=Subject(kind=kind, id=secret.created_by).graph_subject,
                )
            except Exception:
                logger.error(
                    "Could not grant the owner of user secret %s in workspace %s",
                    secret.id,
                    secret.workspace_id,
                    exc_info=True,
                )
                failed += 1
                continue
            secret.graph_granted_at = datetime.now(UTC)
            await session.commit()
            granted += 1
    if granted or skipped or failed:
        logger.info("Secret owners: %d granted, %d skipped, %d failed", granted, skipped, failed)
    return SecretOwnerPass(granted=granted, skipped=skipped, failed=failed)
