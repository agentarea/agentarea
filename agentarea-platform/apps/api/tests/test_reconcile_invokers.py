"""The ownership repair grants an agent's creator ``invoker`` when nobody holds it."""

from types import SimpleNamespace
from uuid import uuid4

from agentarea_agents.domain.models import Agent
from agentarea_common.rebac import ownership_reconcile
from agentarea_common.rebac.models import RelationTuple
from agentarea_common.rebac.ownership_reconcile import (
    TupleWriter,
    reconcile_resource_ownership,
)


class _Graph:
    def __init__(self):
        self.written: list[RelationTuple] = []

    async def write_tuple(self, tuple_: RelationTuple) -> None:
        self.written.append(tuple_)

    async def delete_tuple(self, tuple_: RelationTuple) -> None:
        raise AssertionError("the repair only adds")

    async def query_all_tuples(self, query):
        return []


class _Session:
    def __init__(self, rows):
        self._rows = rows

    async def execute(self, _statement):
        return SimpleNamespace(all=lambda: self._rows)


def _row(owner: str):
    return SimpleNamespace(id=uuid4(), workspace_id="w", created_by=owner)


async def test_attached_agents_without_an_invoker_get_their_creator(monkeypatch):
    monkeypatch.setattr(ownership_reconcile, "load_governed_models", lambda: [Agent])
    granted, revoked_by_someone = _row("alice"), _row("bob")
    graph = _Graph()
    await reconcile_resource_ownership(
        _Session([granted, revoked_by_someone]),
        TupleWriter(graph, dry_run=False),
        {},
        skip={str(granted.id), str(revoked_by_someone.id)},
        invoked={str(revoked_by_someone.id)},
    )
    assert [(t.object, t.relation, t.subject_id) for t in graph.written] == [
        (str(granted.id), "invoker", "User:alice")
    ]


async def test_a_new_agent_gets_ownership_and_invoke_together(monkeypatch):
    monkeypatch.setattr(ownership_reconcile, "load_governed_models", lambda: [Agent])
    fresh = _row("alice")
    graph = _Graph()
    await reconcile_resource_ownership(
        _Session([fresh]), TupleWriter(graph, dry_run=False), {}, skip=set(), invoked=set()
    )
    assert {t.relation for t in graph.written} == {
        "project",
        "reader",
        "writer",
        "manager",
        "invoker",
    }
