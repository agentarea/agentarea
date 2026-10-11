"""The members route says when a removal is not finished yet.

A removal ends the membership in the database and then takes the graph grants
away. When the graph call fails the outbox relay finishes the job, but until it
does the member still has access, so the route must not answer as if they were
gone.
"""

from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.deps.services import get_audit_service
from agentarea_api.api.v1.workspace_invitations import get_membership_service, router
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.workspaces import MemberNotFound
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

OWNER = "owner-user"
WORKSPACE = "ws-acme"


class FakeMemberships:
    def __init__(self, revoked: bool, members: tuple[str, ...] = ("member-user",)) -> None:
        self.revoked = revoked
        self.members = members
        self.calls: list[str] = []

    async def remove(self, *, workspace_id, target_user_id, actor_user_id) -> bool:
        self.calls.append(target_user_id)
        if target_user_id not in self.members:
            raise MemberNotFound("No such member in this workspace.")
        return self.revoked


@pytest.fixture
def audit() -> AsyncMock:
    return AsyncMock()


@pytest.fixture
def app_for(audit):
    def build(revoked: bool, memberships: FakeMemberships | None = None) -> FastAPI:
        app = FastAPI()
        app.include_router(router, prefix="/v1/workspaces/{workspace}")
        app.dependency_overrides[get_user_context] = lambda: UserContext(
            user_id=OWNER, workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE]
        )
        service = memberships or FakeMemberships(revoked)
        app.dependency_overrides[get_membership_service] = lambda: service
        app.dependency_overrides[get_audit_service] = lambda: audit
        return app

    return build


async def _delete(app: FastAPI, user_id: str = "member-user"):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.delete(f"/v1/workspaces/{WORKSPACE}/members/{user_id}")


async def test_a_finished_removal_is_no_content(app_for):
    response = await _delete(app_for(True))

    assert response.status_code == 204


async def test_a_removal_the_graph_has_not_taken_yet_is_accepted_not_done(app_for):
    response = await _delete(app_for(False))

    assert response.status_code == 202
    assert response.json() == {"status": "revocation_pending"}


@pytest.mark.parametrize("revoked", [True, False])
async def test_a_removal_is_audited_whether_or_not_the_graph_caught_up(app_for, audit, revoked):
    """The membership ended in both cases; only access revocation is pending in one."""
    await _delete(app_for(revoked))

    audit.record.assert_awaited_once_with(
        "member.remove",
        "member",
        "member-user",
        event_metadata={"self_removal": False, "access_revoked": revoked},
    )



async def test_removing_a_non_member_is_not_found_and_not_audited(app_for, audit):
    response = await _delete(app_for(True), "nobody-here")

    assert response.status_code == 404
    audit.record.assert_not_awaited()


async def test_an_id_longer_than_any_stored_one_is_refused_before_the_service(app_for, audit):
    """255 is the width of the outbox ``aggregate_id`` a removal would write."""
    memberships = FakeMemberships(True, members=("y" * 256,))

    response = await _delete(app_for(True, memberships), "y" * 256)

    assert response.status_code == 422
    assert memberships.calls == []
    audit.record.assert_not_awaited()
