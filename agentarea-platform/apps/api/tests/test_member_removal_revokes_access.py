"""Removing a member ends every way back in.

Before this, ``WorkspaceMembershipService.remove`` only dropped the graph tuple
and the membership row. The removed user's ``aat_`` keys kept authenticating
into the workspace -- a key's own workspace was trusted as accessible -- and
their accepted invitation stayed redeemable, so replaying the old link
re-recorded membership.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import _validate_api_key
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.base.models import BaseModel
from agentarea_common.di.container import register_singleton
from agentarea_common.rebac import CheckResult, RelationTuple
from agentarea_common.workspaces import (
    INVITATION_STATUS_REVOKED,
    InvitationRevoked,
    Workspace,
    WorkspaceInvitation,
    WorkspaceInvitationRepository,
    WorkspaceInvitationService,
    WorkspaceMembership,
    WorkspaceMembershipRepository,
    WorkspaceMembershipService,
    WorkspaceRepository,
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
