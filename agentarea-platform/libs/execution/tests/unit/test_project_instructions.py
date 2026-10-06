"""A run carries the instructions of the project it runs in, outermost project first."""

import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_agents.domain.models import Agent  # noqa: F401
from agentarea_agents.domain.skill_models import Skill  # noqa: F401
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_execution.activities.agent import config as config_activities
from agentarea_execution.models import AgentConfigRequest
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance  # noqa: F401
from agentarea_projects.application import service as project_service
from agentarea_projects.application.service import ProjectService
from agentarea_projects.domain.models import Project, project_agents
from agentarea_projects.infrastructure.repository import ProjectRepository
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from temporalio.exceptions import ApplicationError

from .test_task_resource_config import activity_context, agent  # noqa: F401

WORKSPACE = "workspace-a"


@pytest.fixture
async def db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync: BaseModel.metadata.create_all(
                sync, tables=[Project.__table__, project_agents]
            )
        )
    async with AsyncSession(engine) as session:
        # Only projects and their links are created: an agent id need not exist,
        # whatever a conftest elsewhere in the run set the pragma to.
        await session.execute(text("PRAGMA foreign_keys=OFF"))
        yield session
    await engine.dispose()


async def _project(db, name, instructions, parent=None, workspace=WORKSPACE):
    project_id = uuid4()
    await db.execute(
        Project.__table__.insert().values(
            id=project_id,
            workspace_id=workspace,
            created_by="user",
            name=name,
            instructions=instructions,
            parent_project_id=parent,
        )
    )
    return project_id


async def _member(db, project_id, agent_id):
    await db.execute(project_agents.insert().values(project_id=project_id, agent_id=agent_id))


async def _load(db, agent_id, project_id=None):
    service = ProjectService(
        ProjectRepository(db, UserContext(user_id="user", workspace_id=WORKSPACE))
    )
    return await service.run_instructions(agent_id, project_id)


async def test_the_runs_project_and_its_ancestors_come_root_first(db):
    root = await _project(db, "Company", "Write in English.")
    middle = await _project(db, "Sales", None, parent=root)
    leaf = await _project(db, "Outbound", "Never send before 9am.", parent=middle)

    assert await _load(db, uuid4(), leaf) == [
        ("Company", "Write in English."),
        ("Outbound", "Never send before 9am."),
    ]


async def test_without_a_run_project_the_agents_only_project_is_used(db):
    agent_id = uuid4()
    project = await _project(db, "Support", "Be brief.")
    await _member(db, project, agent_id)

    assert await _load(db, agent_id) == [("Support", "Be brief.")]


async def test_an_agent_in_several_projects_gets_none_of_them(db, caplog):
    agent_id = uuid4()
    for name in ("Support", "Sales"):
        await _member(db, await _project(db, name, f"{name} rules."), agent_id)

    with caplog.at_level(logging.INFO, logger=project_service.logger.name):
        assert await _load(db, agent_id) == []

    (record,) = [r for r in caplog.records if "several projects" in r.getMessage()]
    assert record.levelno == logging.INFO


async def test_a_malformed_run_project_fails_the_run_without_retrying():
    with pytest.raises(ApplicationError) as raised:
        await config_activities._load_project_instructions(None, uuid4(), "not-a-uuid")

    assert raised.value.non_retryable
    assert "not-a-uuid" in str(raised.value)


async def test_a_project_of_another_workspace_is_never_read(db):
    foreign = await _project(db, "Other", "Leak this.", workspace="workspace-b")

    assert await _load(db, uuid4(), foreign) == []


async def test_a_parent_cycle_ends(db):
    first, second = uuid4(), uuid4()
    for project_id, parent, name in ((first, second, "First"), (second, first, "Second")):
        await db.execute(
            Project.__table__.insert().values(
                id=project_id,
                workspace_id=WORKSPACE,
                created_by="user",
                name=name,
                instructions=f"{name} rules.",
                parent_project_id=parent,
            )
        )

    assert await _load(db, uuid4(), first) == [
        ("Second", "Second rules."),
        ("First", "First rules."),
    ]


def test_project_instructions_are_a_delimited_block_before_the_agents_own():
    rendered = config_activities._with_project_instructions(
        "Do the task", [("Company", "Write in English."), ("Outbound", "Be brief.")]
    )

    assert rendered == (
        "<project_instructions>\n"
        '<project name="Company">\nWrite in English.\n</project>\n'
        '<project name="Outbound">\nBe brief.\n</project>\n'
        "</project_instructions>\n\n"
        "Do the task"
    )
    assert config_activities._with_project_instructions("Do the task", []) == "Do the task"


async def test_project_instructions_reach_the_run_but_not_the_agents_config_hash(
    activity_context,  # noqa: F811
    monkeypatch,
):
    ctx, functions = activity_context
    saved = agent()
    ctx.get_agent_service.return_value.get_with_skills.return_value = saved
    ctx.get_model_instance_service.return_value.get.return_value = SimpleNamespace(
        model_spec=SimpleNamespace(kind="chat", context_window=64000, default_context_strategy=None)
    )
    request = AgentConfigRequest(
        agent_id=saved.id,
        user_context_data={"user_id": "user", "workspace_id": "workspace"},
        execution_context={"project_id": str(uuid4())},
    )
    without = await functions["build_agent_config_activity"](request)
    loader = AsyncMock(return_value=[("Company", "Write in English.")])
    monkeypatch.setattr(config_activities, "_load_project_instructions", loader)

    result = await functions["build_agent_config_activity"](request)

    assert result.instruction.startswith("<project_instructions>")
    assert "Write in English." in result.instruction
    assert "Do the task" in result.instruction
    assert result.config_hash == without.config_hash
    assert loader.await_args.args[1:] == (saved.id, request.execution_context["project_id"])
