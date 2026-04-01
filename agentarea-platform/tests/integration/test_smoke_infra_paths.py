"""Smoke tests for real infrastructure paths (DB + Temporal connectivity)."""

import asyncio
import json
import os
from datetime import timedelta
from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.simple_authorization import SimpleAuthorizationService
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_common.config import get_settings
from agentarea_common.events.broker import EventBroker
from agentarea_common.workflow.temporal_executor import TemporalWorkflowExecutor
from agentarea_execution.models import UpdateTaskStatusResult
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
from agentarea_tasks.domain.models import SimpleTask
from agentarea_tasks.task_service import TaskService
from agentarea_tasks.temporal_task_manager import TemporalTaskManager
from agentarea_tasks.infrastructure.repository import TaskRepository
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from temporalio import activity
from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter
from temporalio.worker import Worker


pytestmark = [
    pytest.mark.integration,
    pytest.mark.smoke,
    pytest.mark.golden,
    pytest.mark.asyncio,
]


async def test_smoke_task_repository_round_trip_real_db():
    """Validate task create/list/get/update path against real DB session."""
    url = (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'postgres')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'postgres')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'aiagents')}"
    )
    suffix = uuid4().hex[:8]
    user_context = UserContext(user_id=f"smoke-user-{suffix}", workspace_id=f"smoke-workspace-{suffix}")
    engine = create_async_engine(url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(BaseModel.metadata.create_all)

        async with session_factory() as session:
            repo = RepositoryFactory(session, user_context).create_repository(TaskRepository)
            agent_id = uuid4()

            created = await repo.create(
                agent_id=agent_id,
                description="smoke repository round trip",
                parameters={"source": "smoke"},
                status="pending",
            )

            listed = await repo.list_tasks(limit=50, offset=0)
            fetched = await repo.get_task(created.id)
            updated = await repo.update_status(created.id, "running")

            assert any(task.id == created.id for task in listed)
            assert fetched is not None
            assert fetched.id == created.id
            assert updated is not None
            assert updated.status == "running"
    finally:
        await engine.dispose()


async def test_smoke_workspace_scope_real_db():
    """Validate workspace isolation filter path against real DB session."""
    url = (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'postgres')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'postgres')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'aiagents')}"
    )
    suffix = uuid4().hex[:8]
    ws1 = UserContext(user_id=f"smoke-u1-{suffix}", workspace_id=f"smoke-ws-1-{suffix}")
    ws2 = UserContext(user_id=f"smoke-u2-{suffix}", workspace_id=f"smoke-ws-2-{suffix}")
    shared_agent_id = uuid4()
    engine = create_async_engine(url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(BaseModel.metadata.create_all)

        async with session_factory() as session:
            repo1 = RepositoryFactory(session, ws1).create_repository(TaskRepository)
            repo2 = RepositoryFactory(session, ws2).create_repository(TaskRepository)

            task_ws1 = await repo1.create(
                agent_id=shared_agent_id,
                description="workspace 1 task",
                parameters={},
                status="pending",
            )
            await repo2.create(
                agent_id=shared_agent_id,
                description="workspace 2 task",
                parameters={},
                status="pending",
            )

            ws1_tasks = await repo1.list_tasks(limit=100, offset=0)
            ws2_view_of_ws1 = await repo2.get_task(task_ws1.id)

            assert any(task.id == task_ws1.id for task in ws1_tasks)
            assert ws2_view_of_ws1 is None
    finally:
        await engine.dispose()


async def test_smoke_temporal_connectivity():
    """Validate real Temporal connectivity and query path."""
    settings = get_settings()
    executor = TemporalWorkflowExecutor(
        namespace=settings.workflow.TEMPORAL_NAMESPACE,
        server_url=settings.workflow.TEMPORAL_SERVER_URL,
    )

    result = await executor.get_workflow_status(f"smoke-missing-{uuid4()}")
    assert result.workflow_id.startswith("smoke-missing-")
    assert result.status is not None


class _NoopEventBroker(EventBroker):
    async def publish(self, event) -> None:
        return None


@pytest.mark.smoke
async def test_smoke_create_agent_and_submit_task_basic_flow():
    """Create an agent and submit a task through Temporal task manager basic flow."""
    url = (
        f"postgresql+asyncpg://{os.getenv('POSTGRES_USER', 'postgres')}:"
        f"{os.getenv('POSTGRES_PASSWORD', 'postgres')}@"
        f"{os.getenv('POSTGRES_HOST', 'localhost')}:"
        f"{os.getenv('POSTGRES_PORT', '5432')}/"
        f"{os.getenv('POSTGRES_DB', 'aiagents')}"
    )
    settings = get_settings()
    user_context = UserContext(
        user_id=f"smoke-user-{uuid4().hex[:6]}",
        workspace_id=f"smoke-ws-{uuid4().hex[:6]}",
    )
    engine = create_async_engine(url, echo=False)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    status_updates: list[dict] = []
    allow_completion = asyncio.Event()

    @activity.defn(name="build_agent_config_activity")
    async def mock_build_agent_config(*args, **kwargs):
        return {
            "id": str(agent.id),
            "name": agent.name,
            "description": agent.description,
            "instruction": agent.instruction,
            "model_id": str(uuid4()),
            "tools": [],
            "events_config": {},
            "planning": False,
        }

    @activity.defn(name="discover_available_tools_activity")
    async def mock_discover_tools(*args, **kwargs):
        return [
            {
                "type": "function",
                "function": {
                    "name": "completion",
                    "description": "Mark task complete",
                    "parameters": {
                        "type": "object",
                        "properties": {"result": {"type": "string"}},
                        "required": ["result"],
                    },
                },
            }
        ]

    @activity.defn(name="call_llm_activity")
    async def mock_call_llm(*args, **kwargs):
        await allow_completion.wait()
        return {
            "role": "assistant",
            "content": "Done",
            "tool_calls": [
                {
                    "id": "call_complete",
                    "type": "function",
                    "function": {
                        "name": "completion",
                        "arguments": json.dumps({"result": "smoke basic flow complete"}),
                    },
                }
            ],
            "cost": 0.001,
            "usage": {"total_tokens": 15},
        }

    @activity.defn(name="execute_mcp_tool_activity")
    async def mock_execute_tool(request):
        tool_name = request.get("tool_name") if isinstance(request, dict) else request.tool_name
        tool_args = request.get("tool_args", {}) if isinstance(request, dict) else request.tool_args
        if tool_name == "completion":
            return {"success": True, "completed": True, "result": tool_args.get("result")}
        return {"success": True, "result": "noop"}

    @activity.defn(name="evaluate_goal_progress_activity")
    async def mock_evaluate_goal(*args, **kwargs):
        return {"goal_achieved": False, "final_response": None}

    @activity.defn(name="publish_workflow_events_activity")
    async def mock_publish_events(*args, **kwargs):
        return True

    @activity.defn(name="update_task_status_activity")
    async def mock_update_task_status(request):
        payload = request if isinstance(request, dict) else request.model_dump()
        status_updates.append(payload)
        return UpdateTaskStatusResult(success=True)

    try:
        async with engine.begin() as conn:
            await conn.run_sync(BaseModel.metadata.create_all)

        async with session_factory() as session:
            factory = RepositoryFactory(session, user_context)
            event_broker = _NoopEventBroker()
            authz = SimpleAuthorizationService()
            agent_service = AgentService(factory, event_broker, authz)
            task_repo = factory.create_repository(TaskRepository)
            task_service = TaskService(
                repository_factory=factory,
                event_broker=event_broker,
                task_manager=TemporalTaskManager(task_repo),
            )

            agent = await agent_service.create_agent(
                name=f"smoke-agent-{uuid4().hex[:6]}",
                description="smoke basic flow agent",
                instruction="Complete the task by calling completion",
                model_id=str(uuid4()),
                tools=[],
                planning=False,
            )

            temporal_client = await Client.connect(
                settings.workflow.TEMPORAL_SERVER_URL,
                namespace=settings.workflow.TEMPORAL_NAMESPACE,
                data_converter=pydantic_data_converter,
            )

            async with Worker(
                temporal_client,
                task_queue="agent-tasks",
                workflows=[AgentExecutionWorkflow],
                activities=[
                    mock_build_agent_config,
                    mock_discover_tools,
                    mock_call_llm,
                    mock_execute_tool,
                    mock_evaluate_goal,
                    mock_publish_events,
                    mock_update_task_status,
                ],
            ):
                submitted = await task_service.submit_task(
                    SimpleTask(
                        title="smoke basic flow task",
                        description="run smoke basic flow",
                        query="say done",
                        user_id=user_context.user_id,
                        agent_id=agent.id,
                        workspace_id=user_context.workspace_id,
                    )
                )
                allow_completion.set()

                assert submitted.status == "running"
                assert submitted.execution_id is not None
                assert submitted.execution_id.startswith("task-")

                for _ in range(40):
                    if any(u.get("status") == "completed" for u in status_updates):
                        break
                    await asyncio.sleep(0.25)

                latest = await task_service.get_task(submitted.id)
                assert latest is not None
                assert latest.status in {"running", "completed"}
                assert latest.execution_id is not None

                # Verify workflow started and can be queried in Temporal by the execution/workflow id.
                temporal_status = await task_service.task_manager.temporal_executor.get_workflow_status(
                    submitted.execution_id
                )
                assert temporal_status.workflow_id == submitted.execution_id
    finally:
        await engine.dispose()
