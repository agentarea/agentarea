"""Record the owner of every user secret made before secrets were graph resources.

A secret created since is granted at create. One created before has no tuples,
so ``can_use_secret`` holds for no one but a workspace admin, and its creator
can no longer wire it in. Granting its ``created_by`` is idempotent; run once
after upgrading, and again harmlessly.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from agentarea_common.auth.context import Subject
from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.rebac.ownership import grant_resource_owner
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EncryptedSecret

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SecretOwner:
    workspace_id: str
    secret_id: str
    created_by: str


async def grant_user_secret_owners(session: AsyncSession, *, dry_run: bool) -> list[SecretOwner]:
    """Grant each user secret's creator ownership; return the secrets it covered."""
    with unscoped("a one-time grant of every workspace's user secrets to their creators"):
        rows = await session.execute(
            select(EncryptedSecret.workspace_id, EncryptedSecret.id, EncryptedSecret.created_by)
            .where(EncryptedSecret.owner_type.is_(None))
            .order_by(EncryptedSecret.workspace_id, EncryptedSecret.id)
        )
    owners = [SecretOwner(str(r.workspace_id), str(r.id), str(r.created_by)) for r in rows]
    if dry_run:
        return owners
    for owner in owners:
        await grant_resource_owner(
            resource_id=owner.secret_id,
            workspace_id=owner.workspace_id,
            owner=Subject(kind="user", id=owner.created_by).graph_subject,
        )
    logger.info("Granted the owners of %d user secrets", len(owners))
    return owners
