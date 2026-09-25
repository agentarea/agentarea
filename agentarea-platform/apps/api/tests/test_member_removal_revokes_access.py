"""Removing a member ends every way back in.

Before this, ``WorkspaceMembershipService.remove`` only dropped the graph tuple
and the membership row. The removed user's ``aat_`` keys kept authenticating
into the workspace -- a key's own workspace was trusted as accessible -- and
their accepted invitation stayed redeemable, so replaying the old link
re-recorded membership.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import _validate_api_key
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.base.models import BaseModel
from agentarea_common.di.container import register_singleton
from agentarea_common.events.outbox_orm import EventOutbox
from agentarea_common.events.outbox_relay import OutboxRelay
from agentarea_common.rebac import (
    CheckResult,
    OpenFGAError,
    OpenFGAUnavailableError,
    RelationTuple,
)
from agentarea_common.workspaces import (
    INVITATION_STATUS_ACCEPTED,
    INVITATION_STATUS_REVOKED,
    MEMBERSHIP_ENDED,
    InvitationRevoked,
    Workspace,
    WorkspaceInvitation,
    WorkspaceInvitationRepository,
    WorkspaceInvitationService,
    WorkspaceMembership,
    WorkspaceMembershipRepository,
    WorkspaceMembershipService,
    WorkspaceRepository,
    membership_removal_handler,
)
from agentarea_mcp.application.access_token_service import hash_token
from agentarea_mcp.domain.auth_models import APIKey
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

OWNER = "owner-user"
MEMBER = "member-user"
WORKSPACE = "ws-acme"
MEMBER_KEY = "aat_member-key-for-acme"  # pragma: allowlist secret
PERSONAL_KEY = "aat_member-personal-key"  # pragma: allowlist secret


class FakeGraph:
    def __init__(self, members: list[tuple[str, str]]) -> None:
        self.tuples = [
            RelationTuple(
                namespace="Workspace", object=ws, relation="members", subject_id=f"User:{user}"
            )
            for ws, user in members
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


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[
                    Workspace.__table__,
                    WorkspaceInvitation.__table__,
                    WorkspaceMembership.__table__,
                    APIKey.__table__,
                    EventOutbox.__table__,
                ],
            )
        )
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as session:
        session.add(Workspace(id=WORKSPACE, slug="acme", name="Acme", owner_user_id=OWNER))
        for raw, workspace_id in ((MEMBER_KEY, WORKSPACE), (PERSONAL_KEY, MEMBER)):
            session.add(
                APIKey(
                    name=raw,
                    token_hash=hash_token(raw),
                    token_prefix=raw[:12],
                    workspace_id=workspace_id,
                    created_by=MEMBER,
                )
            )
        await session.commit()
    try:
        yield factory
    finally:
        await engine.dispose()


@pytest.fixture
def graph() -> FakeGraph:
    return FakeGraph([(WORKSPACE, OWNER), (WORKSPACE, MEMBER)])


@pytest.fixture(autouse=True)
def _wiring(session_factory, graph):
    database = SimpleNamespace(async_session_factory=session_factory)
    with (
        patch("agentarea_common.config.get_database", return_value=database),
        patch(
            "agentarea_common.workspaces.memberships.get_workspace_membership_graph",
            return_value=graph,
        ),
    ):
        yield


async def _authenticate(raw_key: str):
    return await _validate_api_key(raw_key, MagicMock())


def _memberships(session, graph) -> WorkspaceMembershipService:
    return WorkspaceMembershipService(
        membership_repo=WorkspaceMembershipRepository(session),
        workspace_repo=WorkspaceRepository(session),
        graph=graph,
    )


async def test_a_members_key_authenticates_into_the_workspace():
    context = await _authenticate(MEMBER_KEY)

    assert context is not None
    assert (context.user_id, context.workspace_id) == (MEMBER, WORKSPACE)


async def test_a_key_stops_authenticating_once_its_owner_is_no_longer_a_member(graph):
    graph.tuples = [t for t in graph.tuples if t.subject_id != f"User:{MEMBER}"]

    assert await _authenticate(MEMBER_KEY) is None


async def test_a_key_for_the_owners_personal_workspace_needs_no_graph_grant(graph):
    graph.tuples = []

    context = await _authenticate(PERSONAL_KEY)

    assert context is not None
    assert context.workspace_id == MEMBER


async def test_removal_revokes_the_members_keys_for_that_workspace_only(session_factory, graph):
    async with session_factory() as session:
        await _memberships(session, graph).remove(
            workspace_id=WORKSPACE, target_user_id=MEMBER, actor_user_id=OWNER
        )

    async with session_factory() as session:
        keys = {k.name: k.is_active for k in (await session.execute(select(APIKey))).scalars()}
    assert keys == {MEMBER_KEY: False, PERSONAL_KEY: True}
    assert await _authenticate(MEMBER_KEY) is None
    assert await _authenticate(PERSONAL_KEY) is not None


async def test_removal_revokes_the_invitation_so_it_cannot_be_replayed(session_factory, graph):
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    owner = UserContext(user_id=OWNER, workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])
    async with session_factory() as session:
        invitations = WorkspaceInvitationService(WorkspaceInvitationRepository(session))
        memberships = _memberships(session, graph)
        invitation, token = await invitations.create_invitation(actor=owner, workspace_id=WORKSPACE)
        await invitations.accept(token=token, user_id=MEMBER, user_email=None)
        await memberships.record(
            workspace_id=WORKSPACE, user_id=MEMBER, invitation_id=invitation.id
        )

        await memberships.remove(workspace_id=WORKSPACE, target_user_id=MEMBER, actor_user_id=OWNER)

        with pytest.raises(InvitationRevoked):
            await invitations.accept(token=token, user_id=MEMBER, user_email=None)

    async with session_factory() as session:
        stored = (await session.execute(select(WorkspaceInvitation))).scalar_one()
    assert stored.status == INVITATION_STATUS_REVOKED


async def test_the_membership_check_holds_no_database_connection(session_factory, graph):
    """The graph is a network call; a pooled connection must not wait on it."""
    open_sessions = 0

    class _Tracked:
        def __init__(self) -> None:
            self._session = session_factory()

        async def __aenter__(self):
            nonlocal open_sessions
            open_sessions += 1
            return await self._session.__aenter__()

        async def __aexit__(self, *exc):
            nonlocal open_sessions
            open_sessions -= 1
            return await self._session.__aexit__(*exc)

    sessions_during_check: list[int] = []
    real_check = graph.check

    async def check(**kwargs):
        sessions_during_check.append(open_sessions)
        return await real_check(**kwargs)

    graph.check = check
    database = SimpleNamespace(async_session_factory=_Tracked)
    with patch("agentarea_common.config.get_database", return_value=database):
        context = await _authenticate(MEMBER_KEY)

    assert context is not None
    assert sessions_during_check == [0]


def _member_tuples(graph) -> list[RelationTuple]:
    return [t for t in graph.tuples if t.subject_id == f"User:{MEMBER}"]


async def _invite(session) -> tuple[WorkspaceInvitationService, WorkspaceInvitation, str]:
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    owner = UserContext(user_id=OWNER, workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])
    invitations = WorkspaceInvitationService(WorkspaceInvitationRepository(session))
    invitation, token = await invitations.create_invitation(actor=owner, workspace_id=WORKSPACE)
    return invitations, invitation, token


async def test_a_member_removed_before_invitations_were_revoked_cannot_replay(
    session_factory, graph
):
    """Removal used to leave the invitation ACCEPTED; the backfill stamps it granted."""
    graph.tuples = [t for t in graph.tuples if t.subject_id != f"User:{MEMBER}"]
    async with session_factory() as session:
        invitations, invitation, token = await _invite(session)
        invitation.status = INVITATION_STATUS_ACCEPTED
        invitation.accepted_by_user_id = MEMBER
        invitation.accepted_at = datetime(2026, 9, 1)
        invitation.membership_granted_at = datetime(2026, 9, 1)
        await session.commit()

        replayed, _ = await invitations.accept(token=token, user_id=MEMBER, user_email=None)
        await _memberships(session, graph).admit(replayed, MEMBER)

    assert _member_tuples(graph) == []
    async with session_factory() as session:
        assert (await session.execute(select(WorkspaceMembership))).scalars().all() == []


async def test_a_graph_failure_on_accept_is_recovered_by_the_retry(session_factory, graph):
    graph.tuples = [t for t in graph.tuples if t.subject_id != f"User:{MEMBER}"]
    real_write = graph.write_tuple
    failures = [OpenFGAError("graph unavailable")]

    async def flaky_write(relation_tuple):
        if failures:
            raise failures.pop()
        await real_write(relation_tuple)

    graph.write_tuple = flaky_write
    async with session_factory() as session:
        invitations, _, token = await _invite(session)
        memberships = _memberships(session, graph)

        accepted, _ = await invitations.accept(token=token, user_id=MEMBER, user_email=None)
        with pytest.raises(OpenFGAError):
            await memberships.admit(accepted, MEMBER)
        assert accepted.membership_granted_at is None

        retried, _ = await invitations.accept(token=token, user_id=MEMBER, user_email=None)
        await memberships.admit(retried, MEMBER)

    assert len(_member_tuples(graph)) == 2
    async with session_factory() as session:
        row = (await session.execute(select(WorkspaceMembership))).scalar_one()
        stored = (await session.execute(select(WorkspaceInvitation))).scalar_one()
    assert row.user_id == MEMBER
    assert stored.membership_granted_at is not None


async def test_a_removal_racing_the_accept_wins(session_factory, graph):
    graph.tuples = [t for t in graph.tuples if t.subject_id != f"User:{MEMBER}"]
    real_write = graph.write_tuple
    raced: list[bool] = []

    async def write_then_remove(relation_tuple):
        await real_write(relation_tuple)
        if raced:
            return
        raced.append(True)
        async with session_factory() as other:
            await _memberships(other, graph).remove(
                workspace_id=WORKSPACE, target_user_id=MEMBER, actor_user_id=OWNER
            )

    graph.write_tuple = write_then_remove
    async with session_factory() as session:
        invitations, _, token = await _invite(session)
        accepted, _ = await invitations.accept(token=token, user_id=MEMBER, user_email=None)
        with pytest.raises(InvitationRevoked):
            await _memberships(session, graph).admit(accepted, MEMBER)

    assert _member_tuples(graph) == []
    async with session_factory() as session:
        assert (await session.execute(select(WorkspaceMembership))).scalars().all() == []
        stored = (await session.execute(select(WorkspaceInvitation))).scalar_one()
    assert stored.status == INVITATION_STATUS_REVOKED
    assert stored.membership_granted_at is None


class _NoBroadcast:
    async def publish(self, envelope) -> None:
        raise AssertionError(f"{envelope.event_type} is performed by the relay, never broadcast")


def _relay(session_factory, graph) -> OutboxRelay:
    return OutboxRelay(
        session_factory=session_factory,
        event_broker=_NoBroadcast(),
        handlers={MEMBERSHIP_ENDED: membership_removal_handler(graph)},
    )


def _graph_down(graph) -> list[bool]:
    """Make every tuple delete fail until the returned switch is cleared."""
    real_delete = graph.delete_tuple
    down = [True]

    async def delete(relation_tuple):
        if down:
            raise OpenFGAUnavailableError("graph unavailable")
        await real_delete(relation_tuple)

    graph.delete_tuple = delete
    return down


def _grant_member(graph) -> None:
    graph.tuples.append(
        RelationTuple(
            namespace="project",
            object=f"{WORKSPACE}-root",
            relation="reader",
            subject_id=f"User:{MEMBER}",
        )
    )


async def test_a_graph_failure_during_removal_is_finished_by_the_relay(session_factory, graph):
    _grant_member(graph)
    down = _graph_down(graph)

    async with session_factory() as session:
        await _memberships(session, graph).remove(
            workspace_id=WORKSPACE, target_user_id=MEMBER, actor_user_id=OWNER
        )
    assert len(_member_tuples(graph)) == 2, "the graph was down; nothing was revoked yet"

    relay = _relay(session_factory, graph)
    assert await relay.process_batch() == 0
    down.clear()
    assert await relay.process_batch() == 1

    assert _member_tuples(graph) == []
    assert [t.subject_id for t in graph.tuples] == [f"User:{OWNER}"]
    assert await relay.process_batch() == 0, "the revocation is done once, not re-queued"


async def test_removal_is_idempotent(session_factory, graph):
    _grant_member(graph)
    for _ in range(2):
        async with session_factory() as session:
            await _memberships(session, graph).remove(
                workspace_id=WORKSPACE, target_user_id=MEMBER, actor_user_id=OWNER
            )
    relay = _relay(session_factory, graph)
    assert await relay.process_batch() == 2

    assert _member_tuples(graph) == []
    assert [t.subject_id for t in graph.tuples] == [f"User:{OWNER}"]
    async with session_factory() as session:
        assert (await session.execute(select(WorkspaceMembership))).scalars().all() == []


async def test_a_member_admitted_again_keeps_access_the_old_removal_would_take(
    session_factory, graph
):
    async with session_factory() as session:
        memberships = _memberships(session, graph)
        await memberships.remove(workspace_id=WORKSPACE, target_user_id=MEMBER, actor_user_id=OWNER)
        await memberships.record(workspace_id=WORKSPACE, user_id=MEMBER, invitation_id=None)

    assert await _relay(session_factory, graph).process_batch() == 1

    assert len(_member_tuples(graph)) == 2


async def test_a_removal_racing_the_accept_wins_even_when_the_graph_fails(session_factory, graph):
    graph.tuples = [t for t in graph.tuples if t.subject_id != f"User:{MEMBER}"]
    real_write = graph.write_tuple
    raced: list[bool] = []
    real_delete = graph.delete_tuple

    async def write_then_remove(relation_tuple):
        await real_write(relation_tuple)
        if raced:
            return
        raced.append(True)
        _graph_down(graph)
        async with session_factory() as other:
            await _memberships(other, graph).remove(
                workspace_id=WORKSPACE, target_user_id=MEMBER, actor_user_id=OWNER
            )

    graph.write_tuple = write_then_remove
    async with session_factory() as session:
        invitations, _, token = await _invite(session)
        accepted, _ = await invitations.accept(token=token, user_id=MEMBER, user_email=None)
        with pytest.raises(OpenFGAError):
            await _memberships(session, graph).admit(accepted, MEMBER)
    assert _member_tuples(graph), "the accept's grant outlived both failed revocations"

    graph.delete_tuple = real_delete
    assert await _relay(session_factory, graph).process_batch() == 1

    assert _member_tuples(graph) == []
    async with session_factory() as session:
        assert (await session.execute(select(WorkspaceMembership))).scalars().all() == []
        stored = (await session.execute(select(WorkspaceInvitation))).scalar_one()
    assert stored.status == INVITATION_STATUS_REVOKED
    assert stored.membership_granted_at is None
