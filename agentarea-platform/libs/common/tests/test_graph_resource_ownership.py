"""Creating a graph-governed row records its ownership, whoever created it.

Before 2026-09-23 the grant lived at the HTTP route. ``POST /v1/agents``
remembered it; ``agentarea/agents.create`` -- the platform toolset calling the
same ``AgentService`` -- did not, and neither did the three skill-creating tool
methods in ``libs/agents``, which cannot import the API package at all. The
result was a row that ``OpenFGAPermissionService`` fails closed on: its own
creator got 403 on edit and delete.

The grant now hangs off ``WorkspaceScopedRepository.create``, so the question
"did this path remember?" cannot be asked any more.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_common.auth.context import UserContext
from agentarea_common.base.workspace_scoped_repository import WorkspaceScopedRepository
from agentarea_common.rebac import ResourceOwnershipError
from agentarea_common.rebac.models import RelationTuple


@dataclass
class _Row:
    """Stand-in for an ORM row; the repository only reads ``id``."""

    id: str = field(default_factory=lambda: str(uuid4()))
    created_by: str | None = None
    workspace_id: str | None = None

    def __init__(self, **kwargs) -> None:
        self.id = str(uuid4())
        self.created_by = kwargs.get("created_by")
        self.workspace_id = kwargs.get("workspace_id")


class _GovernedRow(_Row):
    __graph_resource__ = True


class _PlainRow(_Row):
    pass


def _repo(model, recorded: list[RelationTuple], monkeypatch) -> WorkspaceScopedRepository:
    session = AsyncMock()
    session.add = lambda record: None
    repo = WorkspaceScopedRepository(
        session=session,
        model_class=model,
        user_context=UserContext(user_id="user-1", workspace_id="ws-acme"),
    )

    client = AsyncMock()
    client.write_tuple.side_effect = lambda tuple_: recorded.append(tuple_)
    monkeypatch.setattr(
        "agentarea_common.rebac.ownership.resolve_graph_client",
        lambda: (client, "OpenFGA"),
    )
    return repo


@pytest.mark.asyncio
async def test_creating_a_governed_row_grants_its_creator_every_bit(monkeypatch) -> None:
    recorded: list[RelationTuple] = []
    repo = _repo(_GovernedRow, recorded, monkeypatch)

    row = await repo.create(name="anything")

    assert [t.relation for t in recorded] == ["project", "reader", "writer", "manager"]
    assert {t.object for t in recorded} == {row.id}
    assert recorded[0].subject_id == "project:ws-acme-root"
    # All three bits explicitly: the model has no roll-up, so `manager` alone
    # would leave the creator unable to read what they just made.
    assert {t.subject_id for t in recorded[1:]} == {"User:user-1"}


@pytest.mark.asyncio
async def test_a_row_that_is_not_graph_governed_writes_no_tuples(monkeypatch) -> None:
    recorded: list[RelationTuple] = []
    repo = _repo(_PlainRow, recorded, monkeypatch)

    await repo.create(name="anything")

    assert recorded == []


@pytest.mark.asyncio
async def test_a_failed_grant_is_raised_not_swallowed(monkeypatch) -> None:
    """A committed row with no tuples is unreachable; silence would hide that."""
    repo = _repo(_GovernedRow, [], monkeypatch)
    monkeypatch.setattr(
        "agentarea_common.rebac.ownership.resolve_graph_client",
        lambda: (_ for _ in ()).throw(ResourceOwnershipError("no client registered")),
    )

    with pytest.raises(ResourceOwnershipError):
        await repo.create(name="anything")
