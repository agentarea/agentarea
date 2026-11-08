"""A turn's token acts for the turn's actor, on its own task, only while the turn runs."""

import contextlib
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock, patch

import jwt
import pytest
from agentarea_common.auth import dependencies, turn_token
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.turn_token import (
    TurnClaims,
    decode_turn_token,
    is_turn_token,
    issue_turn_token,
)
from fastapi import HTTPException, Request

KEY = b"k" * 32
CLAIMS = TurnClaims(
    turn_id="turn-1",
    task_id="task-1",
    workspace_id="ws-1",
    client_id="client-1",
    actor_type="user",
    actor_id="maria",
    on_behalf_of="owner",
)


@pytest.fixture(autouse=True)
def signing_key():
    with patch.object(turn_token, "_signing_key", return_value=KEY):
        yield


class _LiveTurns:
    def __init__(self, *live: str):
        self.live = set(live)

    async def alive(self, turn_id: str) -> bool:
        return turn_id in self.live


def test_the_token_names_actor_client_task_and_turn():
    token = issue_turn_token(CLAIMS, 600)
    payload = jwt.decode(token, KEY, algorithms=["HS256"], audience="task:task-1")

    assert payload["sub"] == "user:maria"
    assert payload["act"] == {"sub": "client:client-1"}
    assert payload["jti"] == "turn-1"
    assert payload["exp"] - payload["iat"] == 600
    assert is_turn_token(token)
    assert decode_turn_token(token) == CLAIMS


def test_a_token_signed_elsewhere_expired_or_not_a_turn_is_refused():
    forged = jwt.encode(
        jwt.decode(issue_turn_token(CLAIMS, 600), options={"verify_signature": False}),
        b"x" * 32,
        algorithm="HS256",
        headers={"kid": turn_token.TURN_TOKEN_KID},
    )
    assert decode_turn_token(forged) is None
    assert decode_turn_token(issue_turn_token(CLAIMS, 60, now=0)) is None
    assert not is_turn_token("aat_key")
    assert not is_turn_token(jwt.encode({"sub": "u"}, KEY, algorithm="HS256"))


def _membership(member: bool):
    @contextlib.asynccontextmanager
    async def session():
        yield Mock()

    return (
        patch(
            "agentarea_common.config.get_database",
            return_value=SimpleNamespace(async_session_factory=session),
        ),
        patch.object(dependencies, "_owns_workspace", AsyncMock(return_value=member)),
        patch.object(dependencies, "_has_graph_membership", AsyncMock(return_value=member)),
    )


AGENT_TURN = TurnClaims(**{**CLAIMS.__dict__, "actor_type": "agent", "actor_id": "agent-1"})


@pytest.mark.asyncio
async def test_a_live_turn_of_an_agent_acts_as_the_agent_under_the_task_owner():
    token = issue_turn_token(AGENT_TURN, 600)
    database, owns, graph = _membership(True)
    with (
        patch.object(dependencies, "live_turns", return_value=_LiveTurns("turn-1")),
        database,
        owns,
        graph,
    ):
        principal = await dependencies._validate_turn_token(token)

    assert principal is not None
    assert principal.user_id == "owner"
    assert principal.subject is not None and principal.subject.kind == "agent"
    assert principal.subject.id == "agent-1"
    assert principal.bound_task_id == "task-1"
    assert principal.turn_client_id == "client-1"
    assert principal.credential is not None and principal.credential.kind == "turn"
    assert principal.credential.key_id == "turn-1"


@pytest.mark.asyncio
async def test_an_agent_turn_stops_acting_once_its_task_owner_left():
    database, owns, graph = _membership(False)
    with (
        patch.object(dependencies, "live_turns", return_value=_LiveTurns("turn-1")),
        database,
        owns,
        graph,
    ):
        assert await dependencies._validate_turn_token(issue_turn_token(AGENT_TURN, 600)) is None


@pytest.mark.asyncio
async def test_the_token_of_a_turn_that_ended_is_refused():
    with patch.object(dependencies, "live_turns", return_value=_LiveTurns()):
        assert await dependencies._validate_turn_token(issue_turn_token(CLAIMS, 600)) is None


@pytest.mark.asyncio
async def test_a_person_who_left_the_workspace_no_longer_acts():
    @contextlib.asynccontextmanager
    async def session():
        yield Mock()

    database = SimpleNamespace(async_session_factory=session)
    with (
        patch.object(dependencies, "live_turns", return_value=_LiveTurns("turn-1")),
        patch("agentarea_common.config.get_database", return_value=database),
        patch.object(dependencies, "_owns_workspace", AsyncMock(return_value=False)),
        patch.object(dependencies, "_has_graph_membership", AsyncMock(return_value=False)),
    ):
        assert await dependencies._validate_turn_token(issue_turn_token(CLAIMS, 600)) is None


def _request(endpoint, task_id: str) -> Request:
    return cast(
        Request, SimpleNamespace(scope={"endpoint": endpoint}, path_params={"task_id": task_id})
    )


def test_the_token_reaches_only_its_own_tasks_marked_routes():
    principal = cast(UserPrincipal, SimpleNamespace(bound_task_id="task-1"))

    @dependencies.admits_turn_token
    async def marked():
        return None

    async def unmarked():
        return None

    dependencies._admit_turn_token(principal, _request(marked, "task-1"))
    for request in (_request(marked, "task-2"), _request(unmarked, "task-1")):
        with pytest.raises(HTTPException) as refused:
            dependencies._admit_turn_token(principal, request)
        assert refused.value.status_code == 403
