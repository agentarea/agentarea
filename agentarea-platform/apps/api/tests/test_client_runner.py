import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_api.api.v1 import harness_runner
from agentarea_api.api.v1.client_mcp import ClientAccessDeniedError, _authorize_client_access
from agentarea_api.api.v1.harness_runner import turn_settings
from agentarea_common.auth.context import UserContext, UserPrincipal
from agentarea_common.exceptions.errors import ConflictError
from agentarea_execution.models import RunnerActor, RunnerTurnEvent, RunnerTurnRequest
from agentarea_mcp.application.client_service import ClientService
from agentarea_mcp.domain.client_models import Client
from agentarea_mcp.infrastructure.runner_presence import PRESENCE_SECONDS, RunnerPresence
from fastapi import status


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


def _connection(
    temporal: object | None = None, websocket: AsyncMock | None = None
) -> harness_runner.RunnerConnection:
    with patch.object(harness_runner, "harness_broker"):
        return harness_runner.RunnerConnection(
            websocket or AsyncMock(),
            client(id=uuid4()),
            UserContext(user_id="maria", workspace_id="ws", workspace_slug="acme"),
            temporal or MagicMock(),
        )


def _held_turn(events: list[RunnerTurnEvent]) -> harness_runner._Turn:
    return harness_runner._Turn(
        turn_id=uuid4(),
        request=RunnerTurnRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            workspace_id="ws",
            iteration=1,
            turn_key="1.1",
            message="go",
        ),
        workflow_id="task-1",
        actor=RunnerActor(type="user", id="maria"),
        finished=asyncio.get_running_loop().create_future(),
        events=events,
    )


def test_one_signal_carries_at_most_its_share_of_a_turns_events():
    big = [
        RunnerTurnEvent(seq=seq, kind="tool.result", item_id=str(seq), output="x" * 200_000)
        for seq in range(1, 6)
    ]
    assert [event.seq for event in harness_runner.signal_batch(big)] == [1, 2]
    huge = [RunnerTurnEvent(seq=1, kind="message", item_id="m", text="x" * 900_000)]
    assert harness_runner.signal_batch(huge) == huge


async def test_a_turns_last_report_is_tried_again_and_sent_in_signals_of_bounded_size():
    temporal = MagicMock()
    signal = AsyncMock(side_effect=[RuntimeError("temporal blip"), None, None, None])
    temporal.get_workflow_handle.return_value.signal = signal
    connection = _connection(temporal)
    turn = _held_turn(
        [
            RunnerTurnEvent(seq=seq, kind="tool.result", item_id=str(seq), output="x" * 200_000)
            for seq in range(1, 6)
        ]
    )
    with (
        patch.object(harness_runner.activity, "heartbeat"),
        patch.object(harness_runner.asyncio, "sleep", AsyncMock()),
    ):
        await connection._report(turn)

    assert signal.await_count == 4
    assert [len(call.args[1].events) for call in signal.await_args_list[1:]] == [2, 2, 1]
    assert turn.events == []


class _DeadWorker:
    def __init__(self, *args, **kwargs) -> None:
        pass

    async def run(self) -> None:
        raise RuntimeError("temporal is unreachable")

    async def shutdown(self) -> None:
        # A worker that failed before it started never finishes a shutdown.
        await asyncio.Event().wait()


async def test_a_socket_whose_worker_died_is_closed_so_its_runner_reconnects():
    websocket = AsyncMock()
    connection = _connection(websocket=websocket)
    frames = iter(['{"type": "hello"}'])

    async def receive() -> str:
        for frame in frames:
            return frame
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    websocket.receive_text = receive

    async def forever() -> None:
        await asyncio.Event().wait()

    with (
        patch.object(harness_runner, "Worker", _DeadWorker),
        patch.object(connection, "_on_hello", AsyncMock()),
        patch.object(connection, "_listen", forever),
        patch.object(connection, "_send_updates", forever),
    ):
        await asyncio.wait_for(connection.serve(), 5)

    websocket.close.assert_awaited_once_with(code=status.WS_1011_INTERNAL_ERROR)
    assert connection.closed


async def test_a_client_agents_run_on_is_not_deleted_under_them():
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=client(id=uuid4()))
    repository.session.scalar = AsyncMock(return_value=2)
    repository.delete = AsyncMock(return_value=True)

    with pytest.raises(ConflictError):
        await ClientService(repository).delete(uuid4())
    repository.delete.assert_not_awaited()

    repository.session.scalar.return_value = 0
    assert await ClientService(repository).delete(uuid4()) is True
