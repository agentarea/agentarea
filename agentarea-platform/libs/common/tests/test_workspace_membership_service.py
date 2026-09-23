"""Tests for workspace membership records and the guards around removal.

Two properties are pinned here:

1. ``joined_at`` comes from a persisted membership row. Before this service
   existed the members endpoint stamped ``datetime.now()`` onto every response,
   so the column reported "today" forever.
2. Removal is guarded. The workspace owner and the last remaining member cannot
   be removed, and a member who is not the owner can only remove themselves.
"""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from agentarea_common.rebac import CheckResult, RelationTuple
from agentarea_common.workspaces import (
    LastMemberRemovalRejected,
    MembershipRemovalForbidden,
    OwnerRemovalRejected,
    Workspace,
    WorkspaceMembership,
    WorkspaceMembershipService,
)

OWNER = "owner-user"
MEMBER = "member-user"
OUTSIDER = "outsider-user"
WORKSPACE = "workspace-1"


class FakeGraph:
    """Minimal stand-in for the Keto/OpenFGA client used by membership helpers."""

    def __init__(self, member_ids: list[str] | None = None) -> None:
        self.tuples: list[RelationTuple] = [
            RelationTuple(
                namespace="Workspace",
                object=WORKSPACE,
                relation="members",
                subject_id=f"User:{member_id}",
            )
            for member_id in member_ids or []
        ]

    async def check(self, *, namespace, object, relation, subject_id) -> CheckResult:
        return CheckResult(
            allowed=any(
                t.namespace == namespace
                and t.object == object
                and t.relation == relation
                and t.subject_id == subject_id
                for t in self.tuples
            )
        )

    async def write_tuple(self, relation_tuple: RelationTuple) -> None:
        self.tuples.append(relation_tuple)

    async def delete_tuple(self, relation_tuple: RelationTuple) -> None:
        self.tuples = [
            t
            for t in self.tuples
            if not (
                t.object == relation_tuple.object
                and t.relation == relation_tuple.relation
                and t.subject_id == relation_tuple.subject_id
            )
        ]

    async def query_all_tuples(self, query) -> list[RelationTuple]:
        return [
            t
            for t in self.tuples
            if (query.namespace is None or t.namespace == query.namespace)
            and (query.object is None or t.object == query.object)
            and (query.relation is None or t.relation == query.relation)
            and (query.subject_id is None or t.subject_id == query.subject_id)
        ]

    def member_ids(self) -> set[str]:
        return {t.subject_id.removeprefix("User:") for t in self.tuples if t.subject_id}


class FakeMembershipRepository:
    def __init__(self, rows: list[WorkspaceMembership] | None = None) -> None:
        self.rows = rows or []

    async def add(self, membership: WorkspaceMembership) -> WorkspaceMembership:
        if membership.created_at is None:
            membership.created_at = datetime.now(UTC).replace(tzinfo=None)
        self.rows.append(membership)
        return membership

    async def get(self, workspace_id: str, user_id: str) -> WorkspaceMembership | None:
        return next(
            (r for r in self.rows if r.workspace_id == workspace_id and r.user_id == user_id),
            None,
        )

    async def list_for_workspace(self, workspace_id: str) -> list[WorkspaceMembership]:
        return [r for r in self.rows if r.workspace_id == workspace_id]

    async def delete(self, workspace_id: str, user_id: str) -> bool:
        row = await self.get(workspace_id, user_id)
        if row is None:
            return False
        self.rows.remove(row)
        return True


class FakeWorkspaceRepository:
    def __init__(self, workspace: Workspace | None = None) -> None:
        self.workspace = workspace

    async def get(self, workspace_id: str) -> Workspace | None:
        if self.workspace is not None and self.workspace.id == workspace_id:
            return self.workspace
        return None


def _workspace(owner_user_id: str = OWNER, workspace_id: str = WORKSPACE) -> Workspace:
    return Workspace(id=workspace_id, slug="ws", name="Workspace", owner_user_id=owner_user_id)


def _membership(user_id: str, joined_at: datetime) -> WorkspaceMembership:
    row = WorkspaceMembership(workspace_id=WORKSPACE, user_id=user_id, invitation_id=None)
    row.created_at = joined_at
    return row


def _service(
    *,
    graph: FakeGraph | None = None,
    memberships: FakeMembershipRepository | None = None,
    workspace: Workspace | None = None,
) -> WorkspaceMembershipService:
    return WorkspaceMembershipService(
        membership_repo=memberships or FakeMembershipRepository(),
        workspace_repo=FakeWorkspaceRepository(workspace if workspace else _workspace()),
        graph=graph or FakeGraph([OWNER, MEMBER]),
    )


# --------------------------------------------------------------------------
# record()
# --------------------------------------------------------------------------


async def test_record_grants_graph_membership_and_persists_the_row():
    graph = FakeGraph()
    memberships = FakeMembershipRepository()
    invitation_id = uuid4()

    await _service(graph=graph, memberships=memberships).record(
        workspace_id=WORKSPACE, user_id=MEMBER, invitation_id=invitation_id
    )

    assert graph.member_ids() == {MEMBER}
    assert len(memberships.rows) == 1
    assert memberships.rows[0].user_id == MEMBER
    assert memberships.rows[0].invitation_id == invitation_id


async def test_record_is_idempotent():
    graph = FakeGraph()
    memberships = FakeMembershipRepository()
    service = _service(graph=graph, memberships=memberships)

    await service.record(workspace_id=WORKSPACE, user_id=MEMBER, invitation_id=None)
    await service.record(workspace_id=WORKSPACE, user_id=MEMBER, invitation_id=None)

    assert len(memberships.rows) == 1
    assert graph.member_ids() == {MEMBER}


# --------------------------------------------------------------------------
# list_members()
# --------------------------------------------------------------------------


async def test_joined_at_comes_from_the_membership_row():
    joined = datetime(2026, 3, 2, 12, 0, 0)
    memberships = FakeMembershipRepository([_membership(MEMBER, joined)])

    members = await _service(graph=FakeGraph([MEMBER]), memberships=memberships).list_members(
        WORKSPACE
    )

    assert [m.user_id for m in members] == [MEMBER]
    assert members[0].joined_at == joined


async def test_member_without_a_row_reports_unknown_join_date():
    members = await _service(
        graph=FakeGraph([MEMBER]), memberships=FakeMembershipRepository()
    ).list_members(WORKSPACE)

    assert members[0].joined_at is None


async def test_members_are_ordered_by_join_date_with_unknowns_last():
    earlier = datetime(2026, 1, 1)
    later = earlier + timedelta(days=30)
    memberships = FakeMembershipRepository(
        [_membership(MEMBER, later), _membership(OWNER, earlier)]
    )

    members = await _service(
        graph=FakeGraph([OWNER, MEMBER, OUTSIDER]), memberships=memberships
    ).list_members(WORKSPACE)

    assert [m.user_id for m in members] == [OWNER, MEMBER, OUTSIDER]


async def test_membership_rows_without_a_graph_tuple_are_not_members():
    """The graph is the source of truth for *who* — a stale row must not resurrect access."""
    memberships = FakeMembershipRepository([_membership(OUTSIDER, datetime(2026, 1, 1))])

    members = await _service(graph=FakeGraph([MEMBER]), memberships=memberships).list_members(
        WORKSPACE
    )

    assert [m.user_id for m in members] == [MEMBER]


# --------------------------------------------------------------------------
# remove()
# --------------------------------------------------------------------------


async def test_owner_cannot_be_removed():
    graph = FakeGraph([OWNER, MEMBER])
    service = _service(graph=graph)

    with pytest.raises(OwnerRemovalRejected):
        await service.remove(workspace_id=WORKSPACE, target_user_id=OWNER, actor_user_id=OWNER)

    assert OWNER in graph.member_ids()


async def test_leaving_a_personal_workspace_is_rejected():
    """A personal workspace is owned by the user it is named after."""
    graph = FakeGraph([OWNER])
    graph.tuples = [
        RelationTuple(
            namespace="Workspace",
            object=OWNER,
            relation="members",
            subject_id=f"User:{OWNER}",
        )
    ]
    service = WorkspaceMembershipService(
        membership_repo=FakeMembershipRepository(),
        workspace_repo=FakeWorkspaceRepository(None),
        graph=graph,
    )

    with pytest.raises(OwnerRemovalRejected):
        await service.remove(workspace_id=OWNER, target_user_id=OWNER, actor_user_id=OWNER)

    assert graph.member_ids() == {OWNER}


async def test_last_member_cannot_be_removed():
    graph = FakeGraph([MEMBER])
    service = _service(graph=graph, workspace=_workspace(owner_user_id="departed-owner"))

    with pytest.raises(LastMemberRemovalRejected):
        await service.remove(workspace_id=WORKSPACE, target_user_id=MEMBER, actor_user_id=MEMBER)

    assert graph.member_ids() == {MEMBER}


async def test_non_owner_cannot_remove_someone_else():
    graph = FakeGraph([OWNER, MEMBER, OUTSIDER])
    service = _service(graph=graph)

    with pytest.raises(MembershipRemovalForbidden):
        await service.remove(workspace_id=WORKSPACE, target_user_id=OUTSIDER, actor_user_id=MEMBER)

    assert OUTSIDER in graph.member_ids()


async def test_member_can_leave_and_the_row_goes_with_them():
    graph = FakeGraph([OWNER, MEMBER])
    memberships = FakeMembershipRepository([_membership(MEMBER, datetime(2026, 1, 1))])
    service = _service(graph=graph, memberships=memberships)

    await service.remove(workspace_id=WORKSPACE, target_user_id=MEMBER, actor_user_id=MEMBER)

    assert graph.member_ids() == {OWNER}
    assert memberships.rows == []


async def test_owner_can_remove_another_member():
    graph = FakeGraph([OWNER, MEMBER])
    service = _service(graph=graph)

    await service.remove(workspace_id=WORKSPACE, target_user_id=MEMBER, actor_user_id=OWNER)

    assert graph.member_ids() == {OWNER}
