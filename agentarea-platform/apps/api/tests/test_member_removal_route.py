"""The members route says when a removal is not finished yet.

A removal ends the membership in the database and then takes the graph grants
away. When the graph call fails the outbox relay finishes the job, but until it
does the member still has access, so the route must not answer as if they were
gone.
"""

import pytest
from agentarea_api.api.v1.workspace_invitations import get_membership_service, router
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

OWNER = "owner-user"
WORKSPACE = "ws-acme"


class FakeMemberships:
    def __init__(self, revoked: bool) -> None:
        self.revoked = revoked

    async def remove(self, *, workspace_id, target_user_id, actor_user_id) -> bool:
        return self.revoked


@pytest.fixture
def app_for():
    def build(revoked: bool) -> FastAPI:
        app = FastAPI()
        app.include_router(router, prefix="/v1")
        app.dependency_overrides[get_user_context] = lambda: UserContext(
            user_id=OWNER, workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE]
        )
        app.dependency_overrides[get_membership_service] = lambda: FakeMemberships(revoked)
        return app

    return build


async def _delete(app: FastAPI):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.delete(f"/v1/workspaces/{WORKSPACE}/members/member-user")


async def test_a_finished_removal_is_no_content(app_for):
    response = await _delete(app_for(True))

    assert response.status_code == 204


async def test_a_removal_the_graph_has_not_taken_yet_is_accepted_not_done(app_for):
    response = await _delete(app_for(False))

    assert response.status_code == 202
    assert response.json() == {"status": "revocation_pending"}
