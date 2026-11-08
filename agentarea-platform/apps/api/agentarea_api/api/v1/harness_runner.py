"""A harness client's runner: one outbound socket for its turns, and its task files.

A runner holds a key issued for its client (an API key bound to the client) and
opens one WebSocket to the platform, so the machine it runs on needs no inbound
access (ADR-0051). A task of an agent on the client runs as an ordinary task
workflow; each of its turns is a ``run_runner_turn`` activity on the client's
task queue. While the socket is open, this process polls that queue: a turn's
activity hands the turn to the runner, heartbeats while the runner holds it,
signals the workflow what the CLI does, and completes when the runner finishes
the turn. A stop cancels the activity, which stops the CLI's turn; a lost socket
fails it, and the workflow assigns the turn again. Messages and approval answers
the workflow sends during a turn arrive on the client's broadcast channel.
Nothing but a runner key of the client reaches these routes; the key names the client.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import mimetypes
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.domain.models import Agent
from agentarea_api.api.v1.clients import client_mcp_path
from agentarea_common.auth.context import UserContext, UserPrincipal
from agentarea_common.auth.context_manager import ContextManager
from agentarea_common.auth.dependencies import (
    authenticate_principal,
    authenticate_runner_key,
    bind_request_workspace,
    binds_workspace,
    enter_as_runner,
)
from agentarea_common.auth.route_authz import AUTHZ_ATTR
from agentarea_common.auth.turn_token import TurnClaims, issue_turn_token, live_turns
from agentarea_common.base import RepositoryFactoryDep
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.base.tenant_scope import bind_workspace_scope, unscoped
from agentarea_common.config import ObservabilitySettings, get_database, temporal_connect_config
from agentarea_common.config.database import get_read_db_session
from agentarea_common.events.contract import LLM_CHUNK, TOOL_PROGRESS
from agentarea_common.events.task_stream import broadcast_live, task_event
from agentarea_common.observability import get_temporal_plugins
from agentarea_common.reasoning_effort import reasoning_effort_of
from agentarea_common.workspaces.lookup import workspace_slug_for
from agentarea_execution.activities.agent.runner import runner_channel
from agentarea_execution.models import (
    RUNNER_CLIENT_METADATA_KEY,
    RunnerActor,
    RunnerApprovalAsk,
    RunnerSteerOutcome,
    RunnerTurnEvent,
    RunnerTurnRequest,
    RunnerTurnResult,
    RunnerTurnUpdate,
    runner_task_queue,
)
from agentarea_execution.workflows.agent.runner_turn import RUNNER_LOST
from agentarea_execution.workflows.constants import RUNNER_TURN_TIMEOUT, Activities
from agentarea_mcp.domain.client_models import RUNNER_KINDS
from agentarea_mcp.domain.client_models import Client as HarnessClient
from agentarea_mcp.infrastructure.runner_presence import runner_presence
from agentarea_tasks.harness import (
    HARNESS_MODEL_PARAMETER,
    RUNNER_SESSION_METADATA_KEY,
    HarnessFiles,
    actor_of_task,
    harness_broker,
)
from agentarea_tasks.harness_protocol import (
    LEASE_SECONDS,
    PING_SECONDS,
    ApprovalRequest,
    Hello,
    LiveSnapshots,
    Message,
    MessageDelta,
    Ping,
    ProtocolError,
    SteerAccepted,
    SteerRejected,
    ToolCall,
    ToolProgress,
    ToolResult,
    TurnEvent,
    TurnFinished,
    TurnStarted,
    UpFrame,
    parse_up_frame,
)
from agentarea_tasks.infrastructure.orm import TaskORM
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Request,
    Response,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.exceptions import ApplicationError
from temporalio.worker import Worker

logger = logging.getLogger(__name__)


async def _runner_client(session: AsyncSession, principal: UserPrincipal) -> HarnessClient | None:
    """The client a runner key is bound to, if it is still in the key's workspace."""
    if principal.bound_client_id is None:
        return None
    with unscoped("a runner key names its client; the client's workspace is the one to act in"):
        client = await session.get(HarnessClient, UUID(principal.bound_client_id))
    if client is None or client.workspace_id != principal.bound_workspace_id:
        return None
    return client


@binds_workspace
async def bind_runner_client(
    request: Request,
    principal: UserPrincipal = Depends(authenticate_principal),
    db_session: AsyncSession = Depends(get_read_db_session, scope="function"),
) -> None:
    """Admit only a client's runner key, and act in that client's workspace."""
    if principal.bound_client_id is None:
        raise HTTPException(status_code=403, detail="Only a runner key is accepted")
    client = await _runner_client(db_session, principal)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    bind_request_workspace(
        request,
        client.workspace_id,
        await workspace_slug_for(client.workspace_id),
        client_id=principal.bound_client_id,
    )


setattr(
    bind_runner_client,
    AUTHZ_ATTR,
    {"action": "run", "resource_type": "client", "reason": "the client's own runner key only"},
)

router = APIRouter(
    prefix="/runner",
    tags=["harness runner"],
    dependencies=[Depends(bind_runner_client)],
)
# The socket authenticates in its handler: a WebSocket has no request to bind.
socket_router = APIRouter(prefix="/runner", tags=["harness runner"])

TURN_FILE_MAX_BYTES = 50 * 1024 * 1024
# A runner that connects says hello at once.
HELLO_SECONDS = 30
SIGNAL_POLL_SECONDS = 5.0
# How often a held turn's activity heartbeats, and keeps its token's turn live.
HEARTBEAT_SECONDS = 2.0
# What the CLI did is signalled to the turn's workflow at most this often.
UPDATE_SECONDS = 0.3
# How long a stopped turn waits for its runner to confirm the CLI stopped.
STOP_GRACE_SECONDS = 15.0
# A tool's output as the task log keeps it; the runner uploads the files it made.
TOOL_OUTPUT_MAX_CHARS = 32_000
# The largest frame a runner may send.
FRAME_MAX_CHARS = 1_000_000
# What a turn may report before its workflow has heard any of it.
TURN_PENDING_MAX = 2_000


def turn_settings(
    parameters: dict[str, Any], agent_effort: str | None, client: HarnessClient
) -> tuple[str | None, str | None]:
    """A turn's model (the task's, else the client's) and reasoning level (the task's, else the agent's)."""
    model = parameters.get(HARNESS_MODEL_PARAMETER) or client.default_model
    effort = reasoning_effort_of(parameters) or agent_effort
    return model, effort


async def _instructions(factory: RepositoryFactory, agent: Agent) -> str | None:
    """The agent's instruction followed by each of its skills' SKILL.md."""
    skills = SkillService(repository_factory=factory, user_context=factory.user_context)
    parts = [agent.instruction.strip()] if agent.instruction and agent.instruction.strip() else []
    for skill in agent.skills:
        parts.append(f"## Skill: {skill.name}\n\n{(await skills.read_skill_md(skill)).strip()}")
    return "\n\n".join(parts) or None


def _clipped(output: str) -> str:
    if len(output) <= TOOL_OUTPUT_MAX_CHARS:
        return output
    return output[:TOOL_OUTPUT_MAX_CHARS] + "\n…[output clipped; the full files are the task's]"


_temporal: Client | None = None
_temporal_lock = asyncio.Lock()


async def temporal_client() -> Client:
    """The process's Temporal client, which polls runners' task queues and signals runs."""
    global _temporal
    async with _temporal_lock:
        if _temporal is None:
            _temporal = await Client.connect(
                **temporal_connect_config(),
                data_converter=pydantic_data_converter,
                plugins=get_temporal_plugins(ObservabilitySettings()),
            )
    return _temporal


class RunnerLostError(Exception):
    """The runner holding a turn closed its socket."""


@dataclass
class _Turn:
    """A turn this socket's runner holds, and what it reported that the run has not heard."""

    turn_id: UUID
    request: RunnerTurnRequest
    workflow_id: str
    actor: RunnerActor
    finished: asyncio.Future[TurnFinished]
    events: list[RunnerTurnEvent] = field(default_factory=list)
    approvals: list[RunnerApprovalAsk] = field(default_factory=list)
    steers: list[RunnerSteerOutcome] = field(default_factory=list)
    signalled_actor: bool = False
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def pending(self) -> bool:
        return bool(self.events or self.approvals or self.steers or not self.signalled_actor)


class RunnerConnection:
    """One runner's socket: the turns it holds, and the frames both ways.

    Frames from the runner are handled in order on the socket's own task; the
    client's broadcast channel (a steer, an approval answer) is listened to on
    a second task, and the client's task queue is polled by a Temporal worker
    that lives as long as the socket.
    """

    def __init__(
        self, websocket: WebSocket, client: HarnessClient, context: UserContext, temporal: Client
    ):
        self.websocket = websocket
        self.client_id = client.id
        self.kind = client.kind
        self.context = context
        self.temporal = temporal
        self.capacity = 1
        self.turns: dict[UUID, _Turn] = {}
        self.live = LiveSnapshots()
        self.broker = harness_broker()
        self.closed = False
        self._send_lock = asyncio.Lock()

    async def serve(self) -> None:
        bind_workspace_scope(self.context.workspace_id)
        ContextManager.set_context(self.context)
        try:
            hello = parse_up_frame(await asyncio.wait_for(self._receive(), HELLO_SECONDS))
        except TimeoutError, ValidationError, ProtocolError, WebSocketDisconnect:
            logger.warning("Runner of client %s sent no hello", self.client_id, exc_info=True)
            await self._close(status.WS_1008_POLICY_VIOLATION)
            return
        if not isinstance(hello, Hello):
            logger.warning("Runner of client %s began with %s", self.client_id, hello.type)
            await self._close(status.WS_1008_POLICY_VIOLATION)
            return
        await self._on_hello(hello)
        worker = Worker(
            self.temporal,
            task_queue=runner_task_queue(self.client_id),
            activities=[self.run_runner_turn],
            max_concurrent_activities=self.capacity,
            max_heartbeat_throttle_interval=timedelta(seconds=1),
            default_heartbeat_throttle_interval=timedelta(seconds=1),
            graceful_shutdown_timeout=timedelta(seconds=STOP_GRACE_SECONDS),
        )
        tasks = [
            asyncio.create_task(worker.run()),
            asyncio.create_task(self._listen()),
            asyncio.create_task(self._send_updates()),
        ]
        try:
            while True:
                await self._handle(parse_up_frame(await self._receive()))
        except WebSocketDisconnect:
            logger.info(
                "Runner of client %s disconnected holding %d turns",
                self.client_id,
                len(self.turns),
            )
        except ValidationError, ProtocolError:
            logger.error("Runner of client %s sent a bad frame", self.client_id, exc_info=True)
            await self._close(status.WS_1003_UNSUPPORTED_DATA)
        except Exception:
            logger.error("Runner socket of client %s failed", self.client_id, exc_info=True)
            await self._close(status.WS_1011_INTERNAL_ERROR)
        finally:
            self.closed = True
            for turn in self.turns.values():
                if not turn.finished.done():
                    turn.finished.set_exception(RunnerLostError())
            await worker.shutdown()
            for task in tasks[1:]:
                task.cancel()
            for task in tasks:
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    async def _receive(self) -> str:
        text = await self.websocket.receive_text()
        if len(text) > FRAME_MAX_CHARS:
            raise ProtocolError(f"a frame of {len(text)} characters")
        return text

    @contextlib.asynccontextmanager
    async def _session(self) -> AsyncIterator[AsyncSession]:
        async with get_database().async_session_factory() as session:
            yield session

    async def _send(self, frame: dict[str, Any]) -> None:
        async with self._send_lock:
            await self.websocket.send_text(json.dumps(frame))

    async def _close(self, code: int) -> None:
        with contextlib.suppress(RuntimeError):
            await self.websocket.close(code=code)

    async def _on_hello(self, hello: Hello) -> None:
        self.capacity = hello.capacity
        async with self._session() as session:
            client = await session.get(HarnessClient, self.client_id)
            if client is None:
                raise LookupError(f"client {self.client_id} not found")
            if hello.models is not None:
                client.models = [model.model_dump() for model in hello.models]
            if hello.default_model and client.default_model is None:
                client.default_model = hello.default_model
            await session.commit()
        await runner_presence().mark(self.client_id)
        if hello.turns:
            logger.warning(
                "Runner of client %s reconnected still running %d turns; their runs assign them again",
                self.client_id,
                len(hello.turns),
            )
        await self._send(
            {
                "type": "welcome",
                "client_id": str(self.client_id),
                "workspace": self._workspace_slug(),
                "kind": self.kind,
                "ping_seconds": PING_SECONDS,
                "lease_seconds": LEASE_SECONDS,
                "turns": [],
            }
        )
        logger.info(
            "Runner of client %s connected (capacity %d, %s)",
            self.client_id,
            self.capacity,
            hello.version,
        )

    @activity.defn(name=Activities.RUN_RUNNER_TURN)
    async def run_runner_turn(self, request: RunnerTurnRequest) -> RunnerTurnResult:
        """Run one turn of a task on this socket's runner, until the runner finishes it."""
        if self.closed:
            raise ApplicationError("the runner went away", type=RUNNER_LOST)
        workflow_id = activity.info().workflow_id
        if workflow_id is None:
            raise ApplicationError(
                "a runner's turn is run by its task's workflow",
                type="NoWorkflow",
                non_retryable=True,
            )
        assign, actor = await self._assignment(request)
        turn = _Turn(
            turn_id=uuid4(),
            request=request,
            workflow_id=workflow_id,
            actor=actor,
            finished=asyncio.get_running_loop().create_future(),
        )
        token = issue_turn_token(
            TurnClaims(
                turn_id=str(turn.turn_id),
                task_id=str(request.task_id),
                workspace_id=request.workspace_id,
                client_id=str(self.client_id),
                actor_type=actor.type,
                actor_id=actor.id,
                on_behalf_of=assign["task_user_id"],
            ),
            int(RUNNER_TURN_TIMEOUT.total_seconds()),
        )
        await live_turns().begin(str(turn.turn_id), LEASE_SECONDS)
        self.turns[turn.turn_id] = turn
        logger.info(
            "Turn %s of task %s assigned to the runner of client %s",
            request.turn_key,
            request.task_id,
            self.client_id,
        )
        try:
            await self._send(
                {
                    "type": "turn.assign",
                    "turn_id": str(turn.turn_id),
                    **{key: value for key, value in assign.items() if key != "task_user_id"},
                    "token": token,
                    "mcp_path": client_mcp_path(self.client_id),
                }
            )
            finished = await self._await_finish(turn)
        except asyncio.CancelledError:
            if self.closed or activity.is_worker_shutdown():
                raise ApplicationError("the runner went away", type=RUNNER_LOST) from None
            await self._stop(turn)
            raise
        except RunnerLostError:
            raise ApplicationError("the runner went away", type=RUNNER_LOST) from None
        except Exception:
            if self.closed:
                logger.warning(
                    "Runner of client %s went away handing over turn %s",
                    self.client_id,
                    request.turn_key,
                    exc_info=True,
                )
                raise ApplicationError("the runner went away", type=RUNNER_LOST) from None
            raise
        finally:
            self.turns.pop(turn.turn_id, None)
            await live_turns().end(str(turn.turn_id))
        await self._signal(turn)
        return RunnerTurnResult(
            status=finished.status, response=finished.response, error=finished.error
        )

    async def _await_finish(self, turn: _Turn) -> TurnFinished:
        while not (await asyncio.wait({turn.finished}, timeout=HEARTBEAT_SECONDS))[0]:
            activity.heartbeat()
            await live_turns().renew(str(turn.turn_id), LEASE_SECONDS)
        return turn.finished.result()

    async def _stop(self, turn: _Turn) -> None:
        """The run was stopped: stop the CLI's turn and record what it did until then."""
        await self._send({"type": "turn.cancel", "turn_id": str(turn.turn_id)})
        done, _ = await asyncio.wait({turn.finished}, timeout=STOP_GRACE_SECONDS)
        if not done or turn.finished.exception() is not None:
            logger.warning(
                "Runner of client %s did not confirm stopping turn %s",
                self.client_id,
                turn.request.turn_key,
            )
        await self._signal(turn)

    async def _assignment(self, request: RunnerTurnRequest) -> tuple[dict[str, Any], RunnerActor]:
        """The turn as the runner needs it: model, instructions, the CLI's session, the actor."""
        async with self._session() as session:
            task = await session.scalar(
                select(TaskORM).where(
                    TaskORM.id == request.task_id,
                    TaskORM.workspace_id == self.context.workspace_id,
                )
            )
            if task is None:
                raise ApplicationError(
                    f"task {request.task_id} not found", type="TaskNotFound", non_retryable=True
                )
            metadata = task.task_metadata or {}
            if metadata.get(RUNNER_CLIENT_METADATA_KEY) != str(self.client_id):
                raise ApplicationError(
                    f"task {request.task_id} does not run on client {self.client_id}",
                    type="WrongClient",
                    non_retryable=True,
                )
            agent = await session.scalar(
                select(Agent).options(selectinload(Agent.skills)).where(Agent.id == task.agent_id)
            )
            client = await session.get(HarnessClient, self.client_id)
            if agent is None or client is None:
                raise ApplicationError(
                    f"agent or client of task {request.task_id} not found",
                    type="TaskNotFound",
                    non_retryable=True,
                )
            model, effort = turn_settings(task.parameters or {}, agent.reasoning_effort, client)
            instructions = await _instructions(RepositoryFactory(session, self.context), agent)
            actor = request.actor or actor_of_task(task.source_identity, task.agent_id)
            assign = {
                "task_id": str(task.id),
                "agent_id": str(task.agent_id),
                "iteration": request.iteration,
                "message": request.message,
                "session_id": metadata.get(RUNNER_SESSION_METADATA_KEY),
                # The person whose CLI profile runs the turn.
                "requested_by": actor.id if actor.type == "user" else task.created_by,
                "actor": actor.model_dump(),
                "model": model,
                "reasoning_effort": effort,
                "instructions": instructions,
                "allow_domains": list(client.allow_domains),
                "task_user_id": task.created_by,
            }
        return assign, actor

    async def _handle(self, frame: UpFrame) -> None:
        if isinstance(frame, Ping):
            await self._on_ping()
            return
        if isinstance(frame, Hello):
            raise ProtocolError("hello sent twice")
        turn = self.turns.get(frame.turn_id)
        if turn is None:
            logger.warning(
                "Runner of client %s sent %s for turn %s it does not hold",
                self.client_id,
                frame.type,
                frame.turn_id,
            )
            return
        if len(turn.events) + len(turn.approvals) + len(turn.steers) >= TURN_PENDING_MAX:
            raise ProtocolError(
                f"turn {turn.request.turn_key} reported more than the run has heard"
            )
        if isinstance(frame, TurnStarted):
            await self._keep_session(turn, frame.session_id)
        elif isinstance(frame, TurnEvent):
            await self._on_event(turn, frame)
        elif isinstance(frame, ApprovalRequest):
            turn.approvals.append(
                RunnerApprovalAsk(
                    request_id=frame.request_id,
                    item_id=frame.item_id,
                    kind=frame.kind,
                    tool_name=frame.tool_name,
                    arguments=frame.arguments,
                    reason=frame.reason,
                )
            )
            await self._signal(turn)
        elif isinstance(frame, SteerAccepted | SteerRejected):
            turn.steers.append(
                RunnerSteerOutcome(
                    message_id=frame.message_id, accepted=isinstance(frame, SteerAccepted)
                )
            )
        elif isinstance(frame, TurnFinished):
            if frame.session_id:
                await self._keep_session(turn, frame.session_id)
            if not turn.finished.done():
                turn.finished.set_result(frame)

    async def _keep_session(self, turn: _Turn, session_id: str) -> None:
        """Keep the CLI's session on the task, so every later turn resumes it."""
        async with self._session() as session:
            task = await session.scalar(
                select(TaskORM)
                .where(
                    TaskORM.id == turn.request.task_id,
                    TaskORM.workspace_id == self.context.workspace_id,
                )
                .with_for_update()
            )
            if task is None:
                raise LookupError(f"task {turn.request.task_id} not found")
            metadata = dict(task.task_metadata or {})
            if metadata.get(RUNNER_SESSION_METADATA_KEY) != session_id:
                metadata[RUNNER_SESSION_METADATA_KEY] = session_id
                task.task_metadata = metadata
            await session.commit()

    async def _on_ping(self) -> None:
        await runner_presence().mark(self.client_id)

    async def _on_event(self, turn: _Turn, frame: TurnEvent) -> None:
        event = frame.event
        if isinstance(event, MessageDelta):
            snapshot = self.live.text(event.item_id, event.text, event.channel)
            if snapshot is not None:
                text, thinking = snapshot
                await self._broadcast(
                    turn,
                    LLM_CHUNK,
                    {
                        "execution_id": turn.workflow_id,
                        "iteration": turn.request.iteration,
                        "item_id": event.item_id,
                        "chunk": text,
                        "thinking": thinking,
                        "chunk_index": frame.seq,
                        "is_final": False,
                        "chunk_type": event.channel,
                    },
                )
            return
        if isinstance(event, ToolProgress):
            output = self.live.output(event.id, event.output)
            if output is not None:
                await self._broadcast(
                    turn,
                    TOOL_PROGRESS,
                    {"tool_name": event.name, "tool_call_id": event.id, "message": output},
                )
            return
        if isinstance(event, Message):
            turn.events.append(
                RunnerTurnEvent(
                    seq=frame.seq,
                    kind="message",
                    item_id=event.item_id,
                    text=event.text,
                    model=event.model,
                )
            )
            self.live.forget(event.item_id)
        elif isinstance(event, ToolCall):
            turn.events.append(
                RunnerTurnEvent(
                    seq=frame.seq,
                    kind="tool.call",
                    item_id=event.id,
                    name=event.name,
                    arguments=event.arguments,
                )
            )
        elif isinstance(event, ToolResult):
            turn.events.append(
                RunnerTurnEvent(
                    seq=frame.seq,
                    kind="tool.result",
                    item_id=event.id,
                    name=event.name,
                    output=_clipped(event.output),
                    success=event.success,
                    exit_code=event.exit_code,
                )
            )
            self.live.forget(event.id)

    async def _broadcast(self, turn: _Turn, event_type: str, data: dict[str, Any]) -> None:
        await broadcast_live(
            self.broker,
            task_event(
                task_id=str(turn.request.task_id),
                workspace_id=self.context.workspace_id,
                event_type=event_type,
                event_id=str(uuid4()),
                timestamp=datetime.now(UTC),
                data={"task_id": str(turn.request.task_id), **data},
            ),
        )

    async def _signal(self, turn: _Turn) -> None:
        """Tell the turn's workflow what the runner reported since the last time."""
        async with turn.lock:
            if not turn.pending:
                return
            update = RunnerTurnUpdate(
                turn_key=turn.request.turn_key,
                actor=turn.actor,
                events=list(turn.events),
                approvals=list(turn.approvals),
                steers=list(turn.steers),
            )
            await self.temporal.get_workflow_handle(turn.workflow_id).signal(
                "runner_turn_update", update
            )
            del turn.events[: len(update.events)]
            del turn.approvals[: len(update.approvals)]
            del turn.steers[: len(update.steers)]
            turn.signalled_actor = True

    async def _send_updates(self) -> None:
        """Signal each held turn's workflow what is new; a failed signal is tried again."""
        while True:
            await asyncio.sleep(UPDATE_SECONDS)
            for turn in list(self.turns.values()):
                if not turn.pending:
                    continue
                try:
                    await self._signal(turn)
                except Exception:
                    logger.error(
                        "Could not signal run %s what turn %s did; trying again",
                        turn.workflow_id,
                        turn.request.turn_key,
                        exc_info=True,
                    )

    def _workspace_slug(self) -> str:
        if self.context.workspace_slug is None:
            raise RuntimeError(f"the runner of client {self.client_id} entered no workspace slug")
        return self.context.workspace_slug

    async def _listen(self) -> None:
        """Relay the client's broadcast messages for the turns this socket holds."""
        live = await self.broker.open_live()
        try:
            await live.subscribe(runner_channel(str(self.client_id)))
            while True:
                message = await live.next_message(SIGNAL_POLL_SECONDS)
                if message is not None:
                    await self._on_delivery(message[1])
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.error(
                "Deliveries to the runner of client %s failed; closing its socket",
                self.client_id,
                exc_info=True,
            )
            await self._close(status.WS_1011_INTERNAL_ERROR)
        finally:
            await live.aclose()

    async def _on_delivery(self, fields: dict[str, str]) -> None:
        turn = next(
            (
                held
                for held in self.turns.values()
                if str(held.request.task_id) == fields["task_id"]
                and held.request.turn_key == fields["turn_key"]
            ),
            None,
        )
        if turn is None:
            return
        kind = fields["kind"]
        if kind == "steer":
            await self._send(
                {
                    "type": "turn.steer",
                    "turn_id": str(turn.turn_id),
                    "message_id": fields["message_id"],
                    "text": fields["text"],
                }
            )
        elif kind == "pause":
            await self._send({"type": "turn.cancel", "turn_id": str(turn.turn_id)})
        elif kind == "decision":
            await self._send(
                {
                    "type": "approval.decision",
                    "turn_id": str(turn.turn_id),
                    "request_id": fields["request_id"],
                    "approved": fields["approved"] == "true",
                }
            )
        else:
            raise ValueError(f"unknown delivery {kind!r} to a runner")


@socket_router.websocket("/connect")
async def connect_runner(websocket: WebSocket) -> None:
    """The runner's socket: turns go down as their runs reach them, what the CLI does comes up.

    Only a client's runner key, as ``Authorization: Bearer``, opens it, for that client.
    """
    scheme, _, token = websocket.headers.get("authorization", "").partition(" ")
    principal = (
        await authenticate_runner_key(token, websocket)
        if scheme.lower() == "bearer" and token
        else None
    )
    if principal is None:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    async with get_database().async_session_factory() as session:
        client = await _runner_client(session, principal)
    if client is None or client.kind not in RUNNER_KINDS:
        logger.warning(
            "Refused the runner socket of client %s: gone or not a runner's kind",
            principal.bound_client_id,
        )
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        return
    context = enter_as_runner(
        principal, client.workspace_id, await workspace_slug_for(client.workspace_id)
    )
    temporal = await temporal_client()
    await websocket.accept()
    await RunnerConnection(websocket, client, context, temporal).serve()


class RunnerIdentity(BaseModel):
    client_id: UUID
    workspace: str
    kind: str


@router.get("/whoami", response_model=RunnerIdentity)
async def runner_whoami(
    factory: RepositoryFactoryDep, principal: UserPrincipal = Depends(authenticate_principal)
) -> RunnerIdentity:
    """The client this runner key serves, so `agentarea runner register` can check the key."""
    client = await _runner_client(factory.session, principal)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")
    return RunnerIdentity(
        client_id=client.id,
        workspace=await workspace_slug_for(client.workspace_id),
        kind=client.kind,
    )


@router.put(
    "/tasks/{task_id}/files/{file_path:path}",
    status_code=204,
)
async def upload_task_file(
    task_id: UUID,
    file_path: str,
    request: Request,
    factory: RepositoryFactoryDep,
    principal: UserPrincipal = Depends(authenticate_principal),
) -> Response:
    """Store a file the CLI made in its task folder, so the task's file links open it."""
    metadata = await factory.session.scalar(
        select(TaskORM.task_metadata).where(
            TaskORM.id == task_id, TaskORM.workspace_id == factory.user_context.workspace_id
        )
    )
    if metadata is None or metadata.get(RUNNER_CLIENT_METADATA_KEY) != principal.bound_client_id:
        raise HTTPException(status_code=404, detail="Task not found")
    parts = PurePosixPath(file_path).parts
    if not parts or file_path.startswith("/") or any(p in {"", ".", ".."} for p in parts):
        raise HTTPException(status_code=422, detail="File path must be relative")
    body = await request.body()
    if len(body) > TURN_FILE_MAX_BYTES:
        raise HTTPException(status_code=413, detail="File too large")
    path = "/".join(parts)
    await HarnessFiles.from_settings(factory.user_context.workspace_id, task_id).put(
        path, body, mimetypes.guess_type(path)[0] or "application/octet-stream"
    )
    return Response(status_code=204)
