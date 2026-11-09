"""A runner's key reaches its client's runner routes and nothing else (ADR-0051)."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_api.api.v1.harness_runner import bind_runner_client
from agentarea_common.auth import dependencies
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.credential import SESSION
from fastapi import HTTPException

OWNER = "owner-user"
WORKSPACE = "ws-acme"


def _runner_key(client_id: str) -> UserPrincipal:
    return UserPrincipal(user_id=OWNER, bound_workspace_id=WORKSPACE, bound_client_id=client_id)


def _request(path_params: dict | None = None) -> MagicMock:
    request = MagicMock()
    request.state = SimpleNamespace()
    request.path_params = path_params or {}
    return request


async def test_a_runner_key_acts_in_its_workspace_on_a_request_bound_to_its_client():
    client_id = str(uuid4())
    request = _request()
    dependencies.bind_request_workspace(request, WORKSPACE, "acme", client_id=client_id)

    context = await dependencies.get_user_context(request, _runner_key(client_id))

    assert (context.user_id, context.workspace_id) == (OWNER, WORKSPACE)
    assert context.admin_workspaces == []


async def test_a_runner_key_is_refused_on_a_request_bound_to_another_client():
    request = _request()
    dependencies.bind_request_workspace(request, WORKSPACE, "acme", client_id=str(uuid4()))

    with pytest.raises(HTTPException) as refused:
        await dependencies.get_user_context(request, _runner_key(str(uuid4())))

    assert refused.value.status_code == 403


async def test_a_runner_key_is_refused_by_a_workspace_route():
    with pytest.raises(HTTPException) as refused:
        await dependencies.get_user_context(
            _request({"workspace": "acme"}), _runner_key(str(uuid4()))
        )

    assert refused.value.status_code == 403


async def test_a_runner_key_is_refused_by_a_route_that_names_no_workspace():
    with pytest.raises(HTTPException) as refused:
        await dependencies.get_principal(_runner_key(str(uuid4())))

    assert refused.value.status_code == 403


async def test_a_runner_key_is_no_principal_at_the_mcp_and_a2a_edges():
    principal = _runner_key(str(uuid4()))
    with patch.object(dependencies, "_authenticate_token", AsyncMock(return_value=principal)):
        assert await dependencies.resolve_principal_from_token("aat_x", _request()) is None


def _client_lookup(workspace_id: str | None) -> MagicMock:
    session = MagicMock()
    found = None if workspace_id is None else SimpleNamespace(workspace_id=workspace_id)
    session.get = AsyncMock(return_value=found)
    return session


async def test_the_runner_routes_bind_the_workspace_of_the_keys_client():
    client_id = str(uuid4())
    request = _request()
    with patch(
        "agentarea_api.api.v1.harness_runner.workspace_slug_for", AsyncMock(return_value="acme")
    ):
        await bind_runner_client(request, _runner_key(client_id), _client_lookup(WORKSPACE))

    context = await dependencies.get_user_context(request, _runner_key(client_id))
    assert context.workspace_id == WORKSPACE


@pytest.mark.parametrize(
    "principal",
    [
        UserPrincipal(user_id=OWNER, credential=SESSION),
        UserPrincipal(user_id=OWNER, bound_workspace_id=WORKSPACE),
    ],
    ids=["session", "workspace key"],
)
async def test_the_runner_routes_refuse_every_other_credential(principal):
    with pytest.raises(HTTPException) as refused:
        await bind_runner_client(_request(), principal, _client_lookup(WORKSPACE))

    assert refused.value.status_code == 403


@pytest.mark.parametrize("workspace_id", ["ws-other", None], ids=["moved", "deleted"])
async def test_a_runner_key_whose_client_is_not_in_its_workspace_finds_no_client(workspace_id):
    with pytest.raises(HTTPException) as refused:
        await bind_runner_client(
            _request(), _runner_key(str(uuid4())), _client_lookup(workspace_id)
        )

    assert refused.value.status_code == 404
