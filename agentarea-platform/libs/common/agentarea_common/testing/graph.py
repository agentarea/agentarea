"""An in-memory stand-in for the authorization graph, for tests that create rows.

Creating an agent, skill, MCP server or client writes ownership tuples (see
``agentarea_common.rebac.ownership``), and the write is deliberately not
optional: a row without them is unreachable to its own creator. Tests that only
need such a row as scenery would otherwise each have to mock a graph client.

Use this where the graph is *scenery*. Where it is the subject, assert on the
tuples directly -- ``recorded`` is here for that.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..rebac.models import RelationTuple


@dataclass
class RecordingGraph:
    """Collects the tuples written through it, and answers nothing else."""

    recorded: list[RelationTuple] = field(default_factory=list)

    async def write_tuple(self, tuple_: RelationTuple) -> None:
        self.recorded.append(tuple_)

    async def delete_tuple(self, tuple_: RelationTuple) -> None:
        self.recorded = [t for t in self.recorded if t != tuple_]

    def objects_with(self, relation: str) -> set[str]:
        return {t.object for t in self.recorded if t.relation == relation}


def install_graph_ownership_stub(monkeypatch) -> RecordingGraph:
    """Point ownership writes at a RecordingGraph for the duration of a test."""
    graph = RecordingGraph()
    monkeypatch.setattr(
        "agentarea_common.rebac.ownership.resolve_graph_client",
        lambda: (graph, "RecordingGraph"),
    )
    return graph


class AllowAllPermissions:
    """A PDP that allows everything, for tests where authority is not the subject.

    Named for what it does, because the production code has no such mode: since
    2026-09-22 there is no allow-all ``PermissionService`` and the app refuses to
    start without a graph backend. A test that wants the refusal registers its
    own deny, or asserts through ``apps/api/tests/test_task_authority.py`` and
    friends, which exercise the real services.
    """

    async def check(
        self, user_id: str, permission: str, resource_type: str, resource_id: str
    ) -> bool:
        return True


def allow_all_permissions() -> AllowAllPermissions:
    """Register a permissive PDP for the duration of a test module."""
    from ..auth.permission import PermissionService
    from ..di.container import register_singleton

    pdp = AllowAllPermissions()
    register_singleton(PermissionService, pdp)
    return pdp
