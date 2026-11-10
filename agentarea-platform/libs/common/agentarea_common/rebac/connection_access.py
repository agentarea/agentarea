"""Who may call through a connection: its creator, or the whole workspace.

A connection (an MCP server instance or an API connection) is created
personal: the workspace lists it, and only its creator and the agents it was
lent to may call through it. Sharing it with the workspace removes
``personal``; then whoever reads it may use it (``can_use_connection`` in
``openfga/model.fga``). Connections that predate this carry no ``personal``
tuple and stay the workspace's.
"""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from uuid import UUID

from . import ownership
from .models import RelationQuery, RelationTuple
from .ownership import delete_tuple_idempotent, write_tuple_idempotent

PERSONAL_RELATION = "personal"
CONNECTION_USER_RELATION = "connection_user"

# ``personal`` is checked against the caller, so it names every kind of caller.
_EVERYONE = ("User:*", "Agent:*")


def _personal_tuples(connection_id: UUID | str) -> list[RelationTuple]:
    return [
        RelationTuple(
            namespace="resource",
            object=str(connection_id),
            relation=PERSONAL_RELATION,
            subject_id=subject,
        )
        for subject in _EVERYONE
    ]


async def make_personal(connection_id: UUID | str) -> None:
    client = ownership.resolve_graph_client()
    for relationship in _personal_tuples(connection_id):
        await write_tuple_idempotent(client, relationship)


async def share_with_workspace(connection_id: UUID | str) -> None:
    client = ownership.resolve_graph_client()
    for relationship in _personal_tuples(connection_id):
        await delete_tuple_idempotent(client, relationship)


async def personal_connection_ids(connection_ids: Iterable[UUID | str]) -> set[str]:
    """Which of ``connection_ids`` are personal: one read of each one's tuples, concurrently."""
    client = ownership.resolve_graph_client()
    ids = [str(connection_id) for connection_id in connection_ids]

    async def is_personal(connection_id: str) -> bool:
        tuples = await client.query_all_tuples(
            RelationQuery(namespace="resource", object=connection_id)
        )
        return any(t.relation == PERSONAL_RELATION and t.subject_id == _EVERYONE[0] for t in tuples)

    flags = await asyncio.gather(*(is_personal(connection_id) for connection_id in ids))
    return {connection_id for connection_id, personal in zip(ids, flags, strict=True) if personal}


async def is_connection_owner(graph_subject: str, connection_id: UUID | str) -> bool:
    """Whether ``graph_subject`` created the connection: the direct ``manager``.

    Not ``can_manage``: a workspace admin manages every connection, and sharing
    someone's personal account with the workspace is its owner's call alone.
    """
    client = ownership.resolve_graph_client()
    result = await client.check("resource", str(connection_id), "manager", graph_subject)
    return result.allowed


def _lent(connection_id: UUID | str, agent_id: UUID | str) -> RelationTuple:
    return RelationTuple(
        namespace="resource",
        object=str(connection_id),
        relation=CONNECTION_USER_RELATION,
        subject_id=f"Agent:{agent_id}",
    )


async def lend_connection(connection_id: UUID | str, agent_id: UUID | str) -> None:
    """Let an agent call through the connection, whoever runs it."""
    await write_tuple_idempotent(ownership.resolve_graph_client(), _lent(connection_id, agent_id))


async def withdraw_connection(connection_id: UUID | str, agent_id: UUID | str) -> None:
    await delete_tuple_idempotent(ownership.resolve_graph_client(), _lent(connection_id, agent_id))
