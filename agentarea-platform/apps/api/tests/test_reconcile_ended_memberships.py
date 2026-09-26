"""The reconcile script takes back what an ended membership left in the graph.

Before removal queued its graph revocation in the outbox, a graph call that failed
after the membership row was gone left ``Workspace#members`` and the root-project
``reader`` role behind, and nothing ever retried. The membership row is the record
of who is still in, so a grant for a user without one, who does not own the
workspace, is one of those leftovers.
"""

import importlib.util
from pathlib import Path

import pytest
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


def _members(active: dict[str, set[str]], reads: list[str] | None = None):
    async def load(workspace_id: str) -> set[str]:
        if reads is not None:
            reads.append(workspace_id)
        return active.get(workspace_id, set())

    return load


async def _revoke(
    graph: FakeGraph,
    *,
    dry_run: bool = False,
    load=None,
    protected: dict[str, set[str]] | None = None,
) -> int:
    writer = _module._Writer(graph, dry_run)

    async def load_protected(workspace_id: str) -> set[str]:
        return (protected or {}).get(workspace_id, set())

    return await _module._revoke_ended_memberships(
        writer,
        graph,
        load_members=load or _members({WORKSPACE: {MEMBER}}),
        load_protected=load_protected,
        owners={WORKSPACE: OWNER},
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


async def test_members_are_read_per_workspace_right_before_its_tuples_go():
    other = "ws-other"
    graph = FakeGraph(
        [
            *_grants_of(REMOVED),
            _member(other, f"User:{REMOVED}"),
        ]
    )
    reads: list[str] = []
    deleted_when_read: list[int] = []
    load = _members({}, reads)

    async def tracking(workspace_id: str) -> set[str]:
        deleted_when_read.append(len(graph.tuples))
        return await load(workspace_id)

    assert await _revoke(graph, load=tracking) == 3

    assert sorted(reads) == [WORKSPACE, other]
    assert deleted_when_read[0] == 3
    assert deleted_when_read[1] < 3, "the second workspace is read after the first one's deletes"


async def test_a_member_admitted_after_the_grants_were_read_keeps_them():
    graph = FakeGraph(_grants_of(REMOVED))
    admitted: dict[str, set[str]] = {}

    async def load(workspace_id: str) -> set[str]:
        admitted.setdefault(workspace_id, {REMOVED})
        return admitted[workspace_id]

    assert await _revoke(graph, load=load) == 0

    assert graph.tuples == _grants_of(REMOVED)


async def test_a_member_holding_an_accepted_invitation_without_a_row_refuses_the_run():
    other = "ws-other"
    tuples = [*_grants_of(REMOVED), _member(other, f"User:{MEMBER}")]
    graph = FakeGraph(tuples)

    with pytest.raises(_module.RevocationRefused, match=f"User:{REMOVED} in Workspace:{WORKSPACE}"):
        await _revoke(graph, protected={WORKSPACE: {REMOVED}})

    assert graph.tuples == tuples, "nothing is deleted anywhere once the run is refused"


async def test_an_owner_missing_from_the_owners_map_refuses_the_run():
    other = "ws-other"
    tuples = [_member(other, f"User:{OWNER}")]
    graph = FakeGraph(tuples)

    with pytest.raises(_module.RevocationRefused, match=f"Workspace:{other}"):
        await _revoke(graph, protected={other: {OWNER}})

    assert graph.tuples == tuples


def _recorder(outcomes: dict[tuple[str, str], str] | None = None):
    calls: list[tuple[str, str]] = []

    async def record(workspace_id: str, user_id: str) -> str:
        calls.append((workspace_id, user_id))
        return (outcomes or {}).get((workspace_id, user_id), "recorded")

    return record, calls


async def test_backfill_records_every_graph_member_without_a_row():
    graph = FakeGraph(
        [
            *_grants_of(OWNER),
            *_grants_of(MEMBER),
            *_grants_of(REMOVED),
            _member(WORKSPACE, f"Client:{REMOVED}"),
            _member(MEMBER, f"User:{MEMBER}"),
        ]
    )
    record, calls = _recorder()

    outcomes = await _module._backfill_memberships_from_graph(
        graph, record=record, rows={(WORKSPACE, MEMBER)}, owners={WORKSPACE: OWNER}
    )

    assert calls == [(WORKSPACE, REMOVED)]
    assert outcomes == {"recorded": 1, "present": 0, "ended": 0}


async def test_backfill_leaves_an_ended_membership_to_the_revocation(caplog):
    graph = FakeGraph(_grants_of(REMOVED))
    record, _ = _recorder({(WORKSPACE, REMOVED): "ended"})

    outcomes = await _module._backfill_memberships_from_graph(
        graph, record=record, rows=set(), owners={WORKSPACE: OWNER}
    )

    assert outcomes == {"recorded": 0, "present": 0, "ended": 1}
    assert f"User:{REMOVED} in Workspace:{WORKSPACE}: membership ended" in caplog.text


async def test_backfill_reports_a_row_the_graph_does_not_know_and_keeps_it(caplog):
    graph = FakeGraph(_grants_of(OWNER))
    record, calls = _recorder()

    outcomes = await _module._backfill_memberships_from_graph(
        graph,
        record=record,
        rows={(WORKSPACE, REMOVED), (WORKSPACE, OWNER)},
        owners={WORKSPACE: OWNER},
    )

    assert calls == []
    assert outcomes == {"recorded": 0, "present": 0, "ended": 0}
    assert f"User:{REMOVED} in Workspace:{WORKSPACE} has a membership row" in caplog.text
    assert f"User:{OWNER} in Workspace:{WORKSPACE} has a membership row" not in caplog.text
