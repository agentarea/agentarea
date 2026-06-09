from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_agents.application.skill_service import SkillFileInfo, SkillService
from agentarea_api.api.v1.skills import get_skill_service
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from httpx import ASGITransport, AsyncClient


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_skill_service():
    return AsyncMock(spec=SkillService)


@pytest.fixture
def mock_user_context():
    context = MagicMock()
    context.user_id = "test_user"
    context.workspace_id = "test_workspace"
    return context


@pytest.fixture(autouse=True)
def override_dependencies(mock_skill_service, mock_user_context):
    async def _override_skill_service():
        return mock_skill_service

    async def _override_user_context():
        return mock_user_context

    app.dependency_overrides[get_skill_service] = _override_skill_service
    app.dependency_overrides[get_user_context] = _override_user_context
    yield
    app.dependency_overrides.pop(get_skill_service, None)
    app.dependency_overrides.pop(get_user_context, None)


@pytest.mark.asyncio
async def test_list_skills_returns_metadata_only(async_client, mock_skill_service):
    now = datetime.utcnow()
    skill_one = MagicMock()
    skill_one.id = uuid4()
    skill_one.name = "Test Skill"
    skill_one.slug = "test-skill"
    skill_one.description = "Test Description"
    skill_one.source_type = "github"
    skill_one.source_url = "https://github.com/owner/repo"
    skill_one.s3_path = "s3://bucket/skills/test"
    skill_one.network_scope = "private"
    skill_one.workspace_id = "test_workspace"
    skill_one.created_at = now
    skill_one.updated_at = now
    skill_one.content = "# Test Skill"

    skill_two = MagicMock()
    skill_two.id = uuid4()
    skill_two.name = "Second Skill"
    skill_two.slug = "second-skill"
    skill_two.description = "Second Description"
    skill_two.source_type = "zip"
    skill_two.source_url = None
    skill_two.s3_path = "s3://bucket/skills/second"
    skill_two.network_scope = "egress"
    skill_two.workspace_id = "test_workspace"
    skill_two.created_at = now
    skill_two.updated_at = now
    skill_two.content = "# Second Skill"

    mock_skill_service.list_paginated.return_value = ([skill_one, skill_two], 2)

    response = await async_client.get("/v1/skills")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 50
    assert data["has_next"] is False
    assert len(data["items"]) == 2
    first = data["items"][0]
    second = data["items"][1]
    assert first["name"] == "Test Skill"
    assert first["slug"] == "test-skill"
    assert first["description"] == "Test Description"
    assert first["source_type"] == "github"
    assert first["source_url"] == "https://github.com/owner/repo"
    assert first["has_files"] is True
    assert first["network_scope"] == "private"
    assert first["workspace_id"] == "test_workspace"
    assert "content" not in first
    assert second["name"] == "Second Skill"
    assert second["slug"] == "second-skill"
    assert second["description"] == "Second Description"
    assert second["source_type"] == "zip"
    assert second["source_url"] is None
    assert second["has_files"] is True
    assert second["network_scope"] == "egress"
    assert second["workspace_id"] == "test_workspace"
    assert "content" not in second
    mock_skill_service.list_paginated.assert_called_once_with(
        limit=50,
        offset=0,
        search=None,
        source_type=None,
        has_files=None,
        network_scope=None,
        from_registry=None,
    )


@pytest.mark.asyncio
async def test_list_skills_accepts_pagination_and_search(async_client, mock_skill_service):
    mock_skill_service.list_paginated.return_value = ([], 21)

    response = await async_client.get(
        "/v1/skills?page=2&page_size=10&search=github"
        "&source_type=github&has_files=true&network_scope=egress&from_registry=false"
    )

    assert response.status_code == 200
    data = response.json()
    assert data == {
        "items": [],
        "total": 21,
        "page": 2,
        "page_size": 10,
        "has_next": True,
    }
    mock_skill_service.list_paginated.assert_called_once_with(
        limit=10,
        offset=10,
        search="github",
        source_type="github",
        has_files=True,
        network_scope="egress",
        from_registry=False,
    )


@pytest.mark.asyncio
async def test_get_skill_content_returns_full_content(async_client, mock_skill_service):
    skill_id = uuid4()
    skill = MagicMock()
    skill.id = skill_id
    skill.name = "Content Skill"
    skill.content = "---\nname: Content Skill\n---\n# Content Skill\nBody"

    mock_skill_service.get_with_catalog.return_value = skill

    response = await async_client.get(f"/v1/skills/{skill_id}/content")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(skill_id)
    assert data["name"] == "Content Skill"
    assert data["content"] == skill.content


@pytest.mark.asyncio
async def test_list_skill_files_returns_manifest(async_client, mock_skill_service):
    skill_id = uuid4()
    files = [
        SkillFileInfo(path="SKILL.md", size=120, url="https://example.com/skill.md"),
        SkillFileInfo(path="templates/run.sh", size=42, url="https://example.com/run.sh"),
    ]
    mock_skill_service.get_skill_files.return_value = files

    response = await async_client.get(f"/v1/skills/{skill_id}/files?include_urls=true")

    assert response.status_code == 200
    data = response.json()
    assert data["skill_id"] == str(skill_id)
    assert len(data["files"]) == 2
    assert data["files"][0]["path"] == "SKILL.md"
    assert data["files"][0]["url"] == "https://example.com/skill.md"
    mock_skill_service.get_skill_files.assert_called_once_with(
        skill_id, include_urls=True
    )


@pytest.mark.asyncio
async def test_get_skill_file_returns_url(async_client, mock_skill_service):
    skill_id = uuid4()
    mock_skill_service.get_skill_file_url.return_value = "https://example.com/file.txt"

    response = await async_client.get(
        f"/v1/skills/{skill_id}/files/templates/file.txt?redirect=false"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "https://example.com/file.txt"
    mock_skill_service.get_skill_file_url.assert_called_once_with(
        skill_id, "templates/file.txt"
    )
