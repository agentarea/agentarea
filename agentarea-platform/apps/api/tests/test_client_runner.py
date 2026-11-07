from uuid import uuid4

import pytest
from agentarea_api.api.v1.client_mcp import ClientAccessDeniedError, _authorize_client_access
from agentarea_api.api.v1.harness_runner import turn_settings
from agentarea_common.auth.context import UserPrincipal
from agentarea_mcp.domain.client_models import Client
from agentarea_mcp.infrastructure.runner_presence import PRESENCE_SECONDS, RunnerPresence


def client(**fields) -> Client:
    return Client(name="codex", kind="codex", allow_domains=[], **fields)


def test_task_model_and_effort_win_over_the_agent_and_the_client():
    c = client(default_model="gpt-6.1-sol")
    assert turn_settings({"model": "gpt-6-luna", "reasoning_effort": "high"}, "medium", c) == (
        "gpt-6-luna",
        "high",
    )


def test_the_clients_default_model_and_the_agents_effort_when_the_task_names_none():
    assert turn_settings({}, "medium", client(default_model="gpt-6.1-sol")) == (
        "gpt-6.1-sol",
        "medium",
    )
    assert turn_settings({}, None, client(default_model=None)) == (None, None)


class _Redis:
    def __init__(self) -> None:
        self.keys: dict[str, tuple[str, int]] = {}

    async def set(self, key: str, value: str, ex: int) -> None:
        self.keys[key] = (value, ex)

    async def mget(self, keys: list[str]) -> list[str | None]:
        return [self.keys[key][0] if key in self.keys else None for key in keys]


async def test_online_only_while_its_runner_keeps_the_key_alive():
    presence = RunnerPresence("redis://unused")
    redis = _Redis()
    presence._client = redis  # type: ignore[assignment]
    up, down = uuid4(), uuid4()
    await presence.mark(up)
    assert await presence.online([up, down, up]) == {up}
    assert redis.keys[f"runners:online:{up}"][1] == PRESENCE_SECONDS
    assert await presence.online([]) == set()


def _turn(client_id: str) -> UserPrincipal:
    return UserPrincipal(
        user_id="person", bound_workspace_id="ws", bound_task_id="task", turn_client_id=client_id
    )


async def test_a_turn_reaches_the_bundle_of_the_client_whose_runner_holds_it():
    client_id = str(uuid4())
    await _authorize_client_access(_turn(client_id), client_id)


async def test_a_turn_is_refused_another_clients_bundle():
    with pytest.raises(ClientAccessDeniedError):
        await _authorize_client_access(_turn(str(uuid4())), str(uuid4()))
