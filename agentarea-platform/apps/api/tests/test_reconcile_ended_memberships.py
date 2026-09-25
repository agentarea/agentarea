"""The reconcile script takes back what an ended membership left in the graph.

Before removal queued its graph revocation in the outbox, a graph call that failed
after the membership row was gone left ``Workspace#members`` and the root-project
``reader`` role behind, and nothing ever retried. The membership row is the record
of who is still in, so a grant for a user without one, who does not own the
workspace, is one of those leftovers.
"""

import importlib.util
from pathlib import Path

from agentarea_common.rebac import RelationTuple

_SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "20260923_reconcile_resource_authz.py"
_spec = importlib.util.spec_from_file_location("_reconcile_resource_authz", _SCRIPT)
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

WORKSPACE = "ws-acme"
OWNER = "owner-user"
MEMBER = "member-user"
REMOVED = "removed-user"


class FakeGraph:
    def __init__(self, tuples: list[RelationTuple]) -> None:
        self.tuples = list(tuples)

    async def query_all_tuples(self, query) -> list[RelationTuple]:
        return [
            t
            for t in self.tuples
            if (query.namespace is None or t.namespace == query.namespace)
            and (query.object is None or t.object == query.object)
            and (query.relation is None or t.relation == query.relation)
            and (query.subject_id is None or t.subject_id == query.subject_id)
        ]

    async def delete_tuple(self, relation_tuple: RelationTuple) -> None:
        self.tuples.remove(relation_tuple)


def _member(workspace_id: str, subject: str) -> RelationTuple:
    return RelationTuple(
        namespace="Workspace", object=workspace_id, relation="members", subject_id=subject
    )


def _reader(project_id: str, subject: str) -> RelationTuple:
    return RelationTuple(
        namespace="project", object=project_id, relation="reader", subject_id=subject
    )


def _grants_of(user_id: str) -> list[RelationTuple]:
    return [_member(WORKSPACE, f"User:{user_id}"), _reader(f"{WORKSPACE}-root", f"User:{user_id}")]


async def _revoke(graph: FakeGraph, *, dry_run: bool = False) -> int:
    writer = _module._Writer(graph, dry_run)
    return await _module._revoke_ended_memberships(
        writer, graph, members={(WORKSPACE, MEMBER)}, owners={WORKSPACE: OWNER}
    )


async def test_an_ended_membership_loses_both_grants():
    graph = FakeGraph([*_grants_of(OWNER), *_grants_of(MEMBER), *_grants_of(REMOVED)])

    assert await _revoke(graph) == 2

    assert graph.tuples == [*_grants_of(OWNER), *_grants_of(MEMBER)]


async def test_a_personal_workspace_without_a_row_keeps_its_owner():
    personal = [_member(MEMBER, f"User:{MEMBER}"), _reader(f"{MEMBER}-root", f"User:{MEMBER}")]
    graph = FakeGraph(personal)

    assert await _revoke(graph) == 0

    assert graph.tuples == personal


async def test_grants_membership_did_not_make_are_left_alone():
    others = [
        _reader("ws-acme-research", f"User:{REMOVED}"),
        _member(WORKSPACE, f"Client:{REMOVED}"),
        _reader(f"{WORKSPACE}-root", f"Workspace:{WORKSPACE}#members"),
    ]
    graph = FakeGraph(others)

    assert await _revoke(graph) == 0

    assert graph.tuples == others


async def test_a_dry_run_reports_and_deletes_nothing():
    graph = FakeGraph(_grants_of(REMOVED))

    assert await _revoke(graph, dry_run=True) == 2

    assert graph.tuples == _grants_of(REMOVED)
