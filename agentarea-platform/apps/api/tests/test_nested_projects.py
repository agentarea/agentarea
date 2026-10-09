"""A subproject is readable, and a project is never nested under itself."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_agents.domain.models import Agent
from agentarea_agents.domain.skill_models import Skill
from agentarea_api.api.v1.projects import ProjectResponse
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.exceptions.errors import BadRequestError
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_projects.application.service import ProjectService
from agentarea_projects.domain.models import (
    Project,
    project_agents,
    project_mcp_instances,
    project_skills,
)
from agentarea_projects.infrastructure.repository import ProjectRepository
from agentarea_projects.schemas.dto import ProjectUpdate
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

WORKSPACE = "workspace-a"


def test_a_subproject_serializes_its_parent_as_a_string():
    parent_id = uuid4()
    project = SimpleNamespace(
        id=uuid4(),
        workspace_id=WORKSPACE,
        created_by="user",
        name="child",
        description=None,
        instructions=None,
        parent_project_id=parent_id,
        skills=None,
        mcp_instances=None,
        agents=None,
    )

    assert ProjectResponse.model_validate(project).parent_project_id == str(parent_id)


@pytest.fixture
async def service():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync: BaseModel.metadata.create_all(
                sync,
                tables=[
                    Project.__table__,
                    project_agents,
                    project_skills,
                    project_mcp_instances,
                    Agent.__table__,
                    Skill.__table__,
                    MCPServerInstance.__table__,
                ],
            )
        )
    async with AsyncSession(engine) as session:
        await session.execute(text("PRAGMA foreign_keys=OFF"))
        yield ProjectService(
            ProjectRepository(session, UserContext(user_id="user", workspace_id=WORKSPACE))
        )
    await engine.dispose()


async def _project(service, name, parent=None):
    project_id = uuid4()
    await service.repository.session.execute(
        Project.__table__.insert().values(
            id=project_id,
            workspace_id=WORKSPACE,
            created_by="user",
            name=name,
            parent_project_id=parent,
        )
    )
    return project_id


async def test_a_project_cannot_be_its_own_parent(service):
    project = await _project(service, "solo")

    with pytest.raises(BadRequestError):
        await service.update_project(project, ProjectUpdate(parent_project_id=project))


async def test_a_project_cannot_be_nested_under_its_own_subproject(service):
    root = await _project(service, "root")
    child = await _project(service, "child", parent=root)
    grandchild = await _project(service, "grandchild", parent=child)

    with pytest.raises(BadRequestError):
        await service.update_project(root, ProjectUpdate(parent_project_id=grandchild))
