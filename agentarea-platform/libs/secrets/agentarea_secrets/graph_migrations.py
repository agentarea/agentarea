"""Graph migration steps for the secret catalog."""

from __future__ import annotations

import logging

from agentarea_common.auth.context import Subject
from agentarea_common.base.tenant_scope import unscoped
from agentarea_common.constants import PLATFORM_PRINCIPAL_ID
from agentarea_common.rebac.graph_migrations import GraphMigration, GraphProvider
from agentarea_common.rebac.models import RelationTuple
from agentarea_common.rebac.ownership import (
    OWNER_RELATIONS,
    root_project_id,
    write_tuple_idempotent,
)
from sqlalchemy import String, cast, column, select, table
from sqlalchemy.ext.asyncio import AsyncSession

from .models import EncryptedSecret

logger = logging.getLogger(__name__)

# Read by id only; the agents library is not a dependency of this one.
_AGENTS = table("agents", column("id"))


async def grant_secret_owners(session: AsyncSession, graph: GraphProvider) -> None:
    """Make every user secret a graph resource, owned by whoever created it.

    Each goes under its workspace's root project, which gives the workspace's
    admins ``can_use_secret``; its creator -- the agent that created it, or
    else the person -- gets the owner relations a create grants. A secret
    whose creator is the platform principal has no one to own it and gets the
    project tuple only. Tuples already there are left as they are.
    """
    with unscoped("a one-time graph migration of every workspace's user secrets"):
        secrets = (
            await session.execute(
                select(EncryptedSecret.id, EncryptedSecret.workspace_id, EncryptedSecret.created_by)
                .where(EncryptedSecret.owner_type.is_(None))
                .order_by(EncryptedSecret.workspace_id, EncryptedSecret.id)
            )
        ).all()
        if not secrets:
            return
        creators = {row.created_by for row in secrets}
        agents = set(
            (
                await session.execute(
                    select(cast(_AGENTS.c.id, String)).where(
                        cast(_AGENTS.c.id, String).in_(creators)
                    )
                )
            ).scalars()
        )
    client = await graph()
    for row in secrets:
        resource = str(row.id)
        await write_tuple_idempotent(
            client,
            RelationTuple(
                namespace="resource",
                object=resource,
                relation="project",
                subject_id=f"project:{root_project_id(row.workspace_id)}",
            ),
        )
        if not row.created_by or row.created_by == PLATFORM_PRINCIPAL_ID:
            logger.warning(
                "User secret %s in workspace %s has no creator to own it; its project only",
                row.id,
                row.workspace_id,
            )
            continue
        owner = Subject(
            kind="agent" if row.created_by in agents else "user", id=row.created_by
        ).graph_subject
        for relation in OWNER_RELATIONS:
            await write_tuple_idempotent(
                client,
                RelationTuple(
                    namespace="resource", object=resource, relation=relation, subject_id=owner
                ),
            )
    logger.info("Recorded the owners of %d user secrets in the graph", len(secrets))


SECRET_OWNERS = GraphMigration(
    id="20261109_2300_secret_owners",
    description="user secrets become graph resources, owned by their creators",
    apply=grant_secret_owners,
)
