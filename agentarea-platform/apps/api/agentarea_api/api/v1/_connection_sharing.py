"""Sharing a connection with the workspace, or taking it back to its owner."""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from typing import Any
from uuid import UUID

from agentarea_agents.infrastructure.repository import AgentRepository
from agentarea_common.auth.context import UserContext
from agentarea_common.rebac.connection_access import (
    is_connection_owner,
    lend_connection,
    make_personal,
    personal_connection_ids,
    share_with_workspace,
)
from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class ConnectionSharingRequest(BaseModel):
    shared: bool


class ConnectionSharing(BaseModel):
    """Who may call through a connection, as its list and detail show it."""

    # Only its creator, and the agents it was lent to, may call through it.
    personal: bool
    # The caller added it, so the caller decides whether the workspace may use it.
    is_owner: bool


async def sharing_of(
    connections: Iterable[Any], user_context: UserContext
) -> dict[str, ConnectionSharing]:
    rows = list(connections)
    personal = await personal_connection_ids(row.id for row in rows)
    return {
        str(row.id): ConnectionSharing(
            personal=str(row.id) in personal,
            is_owner=row.created_by == user_context.user_id,
        )
        for row in rows
    }


async def _agents_naming(
    session: AsyncSession, user_context: UserContext, connection_id: UUID
) -> list[UUID]:
    agents = await AgentRepository(session, user_context).list_all(include_archived=True)
    return [
        agent.id for agent in agents if str(connection_id) in json.dumps(agent.tools, default=str)
    ]


async def set_sharing(
    connection_id: UUID, shared: bool, user_context: UserContext, session: AsyncSession
) -> None:
    """Share the connection with the workspace, or make it its owner's again.

    Only its owner may: a workspace admin manages every connection, but sharing
    someone's own account is theirs to decide. Agents that already call through
    it keep it when it turns personal: attaching it was its owner's loan.
    """
    if not await is_connection_owner(user_context.graph_subject, connection_id):
        raise HTTPException(
            status_code=403,
            detail="Only whoever added this connection can change who may use it.",
        )
    if shared:
        await share_with_workspace(connection_id)
    else:
        for agent_id in await _agents_naming(session, user_context, connection_id):
            await lend_connection(connection_id, agent_id)
        await make_personal(connection_id)
    logger.info(
        "Connection %s %s by %s",
        connection_id,
        "shared with the workspace" if shared else "made personal",
        user_context.user_id,
    )
