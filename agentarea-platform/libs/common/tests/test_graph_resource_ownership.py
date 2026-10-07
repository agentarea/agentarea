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
from unittest.mock import AsyncMock, MagicMock
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
        lambda: client,
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


@pytest.mark.asyncio
async def test_the_grant_lands_before_the_commit(monkeypatch) -> None:
    """A row is committed only once the graph holds its tuples."""
    events: list[str] = []
    recorded: list[RelationTuple] = []
    repo = _repo(_GovernedRow, recorded, monkeypatch)
    graph = AsyncMock()
    graph.write_tuple.side_effect = lambda tuple_: events.append("grant")
    monkeypatch.setattr("agentarea_common.rebac.ownership.resolve_graph_client", lambda: graph)
    repo.session.commit.side_effect = lambda: events.append("commit")

    await repo.create(name="anything")

    assert events == ["grant"] * 4 + ["commit"]


@pytest.mark.asyncio
async def test_a_failed_grant_commits_nothing(monkeypatch) -> None:
    """The retry that follows a 503 must not find a first, unreachable copy."""
    repo = _repo(_GovernedRow, [], monkeypatch)
    monkeypatch.setattr(
        "agentarea_common.rebac.ownership.resolve_graph_client",
        lambda: (_ for _ in ()).throw(ResourceOwnershipError("no client registered")),
    )

    with pytest.raises(ResourceOwnershipError):
        await repo.create(name="anything")

    repo.session.commit.assert_not_awaited()
    repo.session.rollback.assert_awaited_once()


def _deletable(repo: WorkspaceScopedRepository, row: _Row, monkeypatch) -> None:
    monkeypatch.setattr(
        "agentarea_common.base.workspace_scoped_repository.select", lambda *_: MagicMock()
    )
    monkeypatch.setattr(repo, "_get_workspace_filter", lambda: True)
    monkeypatch.setattr(repo.model_class, "id", MagicMock(), raising=False)
    result = MagicMock()
    result.scalar_one_or_none.return_value = row
    repo.session.execute = AsyncMock(return_value=result)


@pytest.mark.asyncio
async def test_deleting_a_governed_row_removes_its_tuples(monkeypatch) -> None:
    row = _GovernedRow()
    held = [
        RelationTuple(
            namespace="resource", object=row.id, relation="project", subject_id="project:ws-root"
        ),
        RelationTuple(namespace="resource", object=row.id, relation="reader", subject_id="User:u"),
    ]
    repo = _repo(_GovernedRow, [], monkeypatch)
    graph = AsyncMock()
    graph.query_all_tuples.return_value = held
    monkeypatch.setattr("agentarea_common.rebac.ownership.resolve_graph_client", lambda: graph)
    _deletable(repo, row, monkeypatch)

    assert await repo.delete(row.id) is True

    query = graph.query_all_tuples.await_args.args[0]
    assert (query.namespace, query.object) == ("resource", row.id)
    assert [c.args[0] for c in graph.delete_tuple.await_args_list] == held


@pytest.mark.asyncio
async def test_a_graph_failure_after_the_delete_is_logged_not_raised(monkeypatch, caplog) -> None:
    """The row is gone; tuples on an id that no longer exists grant nothing."""
    row = _GovernedRow()
    repo = _repo(_GovernedRow, [], monkeypatch)
    graph = AsyncMock()
    graph.query_all_tuples.side_effect = RuntimeError("graph unreachable")
    monkeypatch.setattr("agentarea_common.rebac.ownership.resolve_graph_client", lambda: graph)
    _deletable(repo, row, monkeypatch)

    assert await repo.delete(row.id) is True
    repo.session.commit.assert_awaited_once()
    assert "could not remove its graph tuples" in caplog.text


@pytest.mark.asyncio
async def test_deleting_a_plain_row_never_touches_the_graph(monkeypatch) -> None:
    repo = _repo(_PlainRow, [], monkeypatch)
    graph = AsyncMock()
    monkeypatch.setattr("agentarea_common.rebac.ownership.resolve_graph_client", lambda: graph)
    _deletable(repo, _PlainRow(), monkeypatch)

    assert await repo.delete("any") is True
    graph.query_all_tuples.assert_not_awaited()
