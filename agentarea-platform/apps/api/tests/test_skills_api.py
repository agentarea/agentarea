from datetime import datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from agentarea_agents.application.skill_service import SkillFileInfo, SkillService
from agentarea_api.api.v1.skills import get_skill_service
from agentarea_api.main import app
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.di.container import get_container
from agentarea_common.testing.flows import MainFlow
from httpx import ASGITransport, AsyncClient


@pytest.fixture(autouse=True)
def graph():
    """Ownership grants and list filtering both need a graph client.

    ``AGENTAREA_AUTHZ_BACKEND`` no longer has a "disabled" value, so the grant
    path is always live and answers 503 when the client is missing — which is
    the point. Tests that create resources register a stub instead of relying on
    authorization being switched off.

    ``list_objects`` starts empty, which is the honest default: a caller the
    graph has never heard of may read nothing. Tests that expect rows back say
    which ids are readable.
    """
    from agentarea_common.rebac.openfga_client import OpenFGAClient

    client = AsyncMock(spec=OpenFGAClient)
    client.list_objects.return_value = []
    container = get_container()
    container.register_singleton(OpenFGAClient, client)
    yield client
    container.clear()


@pytest_asyncio.fixture
async def async_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


@pytest.fixture
def mock_skill_service(mock_user_context):
    service = AsyncMock(spec=SkillService)
    service.user_context = mock_user_context
    return service


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


@pytest.mark.flow(MainFlow.SKILLS)
@pytest.mark.asyncio
async def test_list_skills_returns_metadata_only(async_client, mock_skill_service, graph):
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
    graph.list_objects.return_value = [str(skill_one.id), str(skill_two.id)]

    response = await async_client.get("/v1/workspaces/acme/skills")

    assert response.status_code == 200
    data = response.json()
    assert data["total"] == 2
    assert data["page"] == 1
    assert data["page_size"] == 50
    assert data["has_next"] is False
    assert len(data["items"]) == 2
    first = data["items"][0]
    second = data["items"][1]
    assert first["created_at"].endswith("Z")
    assert first["name"] == "Test Skill"
    assert first["slug"] == "test-skill"
    assert first["description"] == "Test Description"
    assert first["source_type"] == "github"
    assert first["source_url"] == "https://github.com/owner/repo"
    assert first["network_scope"] == "private"
    assert first["workspace_id"] == "test_workspace"
    assert "content" not in first
    assert second["name"] == "Second Skill"
    assert second["slug"] == "second-skill"
    assert second["description"] == "Second Description"
    assert second["source_type"] == "zip"
    assert second["source_url"] is None
    assert second["network_scope"] == "egress"
    assert second["workspace_id"] == "test_workspace"
    assert "content" not in second
    mock_skill_service.list_paginated.assert_called_once_with(
        limit=50,
        offset=0,
        search=None,
        source_type=None,
        network_scope=None,
        from_registry=None,
        include_catalog=True,
        ids={str(skill_one.id), str(skill_two.id)},
    )


@pytest.mark.asyncio
async def test_list_skills_accepts_pagination_and_search(async_client, mock_skill_service, graph):
    mock_skill_service.list_paginated.return_value = ([], 21)
    graph.list_objects.return_value = ["b1f0a3d6-0000-4000-8000-000000000001"]

    response = await async_client.get(
        "/v1/workspaces/acme/skills?page=2&page_size=10&search=github"
        "&source_type=github&network_scope=egress&from_registry=false"
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
        network_scope="egress",
        from_registry=False,
        include_catalog=True,
        # The readable set is a filter like any other, and it reaches SQL rather
        # than trimming the page afterwards, so `total` stays truthful.
        ids={"b1f0a3d6-0000-4000-8000-000000000001"},
    )


@pytest.mark.asyncio
async def test_list_skills_can_leave_out_the_catalog(async_client, mock_skill_service, graph):
    mock_skill_service.list_paginated.return_value = ([], 0)
    graph.list_objects.return_value = []

    response = await async_client.get("/v1/workspaces/acme/skills?include_catalog=false")

    assert response.status_code == 200
    assert mock_skill_service.list_paginated.call_args.kwargs["include_catalog"] is False


@pytest.mark.asyncio
async def test_get_skill_content_returns_full_content(async_client, mock_skill_service):
    skill_id = uuid4()
    skill = MagicMock()
    skill.id = skill_id
    skill.name = "Content Skill"
    skill.content = "---\nname: Content Skill\n---\n# Content Skill\nBody"

    mock_skill_service.get_with_catalog.return_value = skill

    response = await async_client.get(f"/v1/workspaces/acme/skills/{skill_id}/content")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(skill_id)
    assert data["name"] == "Content Skill"
    assert data["content"] == skill.content


@pytest.mark.asyncio
async def test_install_skill_materializes_catalog_skill(async_client, mock_skill_service):
    skill_id = uuid4()
    now = datetime.utcnow()
    skill = MagicMock()
    skill.id = uuid4()
    skill.name = "Catalog Skill"
    skill.slug = "catalog-skill"
    skill.description = "Catalog description"
    skill.source_type = "content"
    skill.source_url = None
    skill.s3_path = None
    skill.network_scope = "private"
    skill.workspace_id = "test_workspace"
    skill.created_at = now
    skill.updated_at = now
    skill.registry_item_id = skill_id
    skill.is_catalog = False
    skill.update_available = False

    mock_skill_service.install_catalog_skill.return_value = skill

    response = await async_client.post(f"/v1/workspaces/acme/skills/{skill_id}/install")

    assert response.status_code == 200
    data = response.json()
    assert data["id"] == str(skill.id)
    assert data["registry_item_id"] == str(skill_id)
    assert data["is_catalog"] is False
    mock_skill_service.install_catalog_skill.assert_called_once_with(skill_id)


def _installed_skill(created_by: str) -> MagicMock:
    now = datetime.utcnow()
    skill = MagicMock()
    skill.id = uuid4()
    skill.name = "Installed Skill"
    skill.slug = "installed-skill"
    skill.description = "d"
    skill.source_type = "content"
    skill.source_url = None
    skill.s3_path = None
    skill.network_scope = "private"
    skill.workspace_id = "test_workspace"
    skill.created_at = now
    skill.updated_at = now
    skill.registry_item_id = None
    skill.is_catalog = False
    skill.update_available = False
    skill.created_by = created_by
    return skill


@pytest.mark.asyncio
async def test_installing_an_existing_skill_of_another_member_grants_nothing(
    async_client, mock_skill_service, monkeypatch
):
    # install resolves an id that is already a tenant skill to that row; it must
    # not hand the caller ownership of a skill somebody else created.
    grant = AsyncMock()
    monkeypatch.setattr("agentarea_api.api.v1.skills.grant_resource_owner", grant)
    skill = _installed_skill(created_by="another_member")
    mock_skill_service.install_catalog_skill.return_value = skill

    response = await async_client.post(f"/v1/workspaces/acme/skills/{skill.id}/install")

    assert response.status_code == 200
    grant.assert_not_awaited()


@pytest.mark.asyncio
async def test_installing_a_skill_the_caller_forked_reasserts_their_ownership(
    async_client, mock_skill_service, monkeypatch
):
    grant = AsyncMock()
    monkeypatch.setattr("agentarea_api.api.v1.skills.grant_resource_owner", grant)
    skill = _installed_skill(created_by="test_user")
    mock_skill_service.install_catalog_skill.return_value = skill

    response = await async_client.post(f"/v1/workspaces/acme/skills/{uuid4()}/install")

    assert response.status_code == 200
    grant.assert_awaited_once_with(
        resource_id=skill.id, workspace_id="test_workspace", user_id="test_user"
    )


@pytest.mark.asyncio
async def test_update_catalog_skill_content_uses_forked_skill_id(
    async_client, mock_skill_service, monkeypatch
):
    original_catalog_id = uuid4()
    forked_skill_id = uuid4()
    now = datetime.utcnow()

    forked_skill = MagicMock()
    forked_skill.id = forked_skill_id
    forked_skill.name = "Forked Skill"
    forked_skill.slug = "forked-skill"
    forked_skill.description = "Updated description"
    forked_skill.source_type = "content"
    forked_skill.source_url = None
    forked_skill.s3_path = None
    forked_skill.network_scope = "private"
    forked_skill.workspace_id = "test_workspace"
    forked_skill.created_at = now
    forked_skill.updated_at = now
    forked_skill.registry_item_id = original_catalog_id
    forked_skill.is_catalog = False
    forked_skill.update_available = False

    mock_skill_service.update.return_value = forked_skill
    mock_skill_service.set_content.return_value = forked_skill
    monkeypatch.setattr("agentarea_api.api.v1.skills.require_permission", AsyncMock())

    response = await async_client.put(
        f"/v1/workspaces/acme/skills/{original_catalog_id}",
        json={"description": "Updated description", "content": "# New content"},
    )

    assert response.status_code == 200
    mock_skill_service.update.assert_awaited_once()
    mock_skill_service.set_content.assert_awaited_once_with(forked_skill_id, "# New content")


@pytest.mark.asyncio
async def test_list_skill_files_returns_manifest(async_client, mock_skill_service):
    skill_id = uuid4()
    files = [
        SkillFileInfo(path="SKILL.md", size=120, url="https://example.com/skill.md"),
        SkillFileInfo(path="templates/run.sh", size=42, url="https://example.com/run.sh"),
    ]
    mock_skill_service.get_skill_files.return_value = files

    response = await async_client.get(
        f"/v1/workspaces/acme/skills/{skill_id}/files?include_urls=true"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["skill_id"] == str(skill_id)
    assert len(data["files"]) == 2
    assert data["files"][0]["path"] == "SKILL.md"
    assert data["files"][0]["url"] == "https://example.com/skill.md"
    mock_skill_service.get_skill_files.assert_called_once_with(skill_id, include_urls=True)


@pytest.mark.asyncio
async def test_get_skill_file_returns_url(async_client, mock_skill_service):
    skill_id = uuid4()
    mock_skill_service.get_skill_file_url.return_value = "https://example.com/file.txt"

    response = await async_client.get(
        f"/v1/workspaces/acme/skills/{skill_id}/files/templates/file.txt?redirect=false"
    )

    assert response.status_code == 200
    data = response.json()
    assert data["url"] == "https://example.com/file.txt"
    mock_skill_service.get_skill_file_url.assert_called_once_with(skill_id, "templates/file.txt")


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["q" * 256, ""], ids=["too-long", "empty"])
async def test_update_skill_with_a_name_the_column_cannot_hold_is_422(
    async_client, mock_skill_service, monkeypatch, name
):
    monkeypatch.setattr("agentarea_api.api.v1.skills.require_permission", AsyncMock())

    response = await async_client.put(f"/v1/workspaces/acme/skills/{uuid4()}", json={"name": name})

    assert response.status_code == 422
    mock_skill_service.update.assert_not_awaited()


@pytest.mark.asyncio
async def test_create_skill_with_a_name_override_over_the_limit_is_422(
    async_client, mock_skill_service
):
    response = await async_client.post(
        "/v1/workspaces/acme/skills", json={"content": "# a", "name": "n" * 256}
    )

    assert response.status_code == 422
    mock_skill_service.create_from_content.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_member_with_an_order_past_int32_is_422(async_client, mock_skill_service):
    from agentarea_common.testing import allow_all_permissions

    allow_all_permissions()
    response = await async_client.post(
        f"/v1/workspaces/acme/skills/{uuid4()}/members",
        json={"child_skill_id": str(uuid4()), "order": 2**40},
    )

    assert response.status_code == 422
    mock_skill_service.add_member.assert_not_awaited()


@pytest.mark.asyncio
async def test_uploading_a_file_that_is_not_a_zip_is_400(
    async_client, mock_skill_service, mock_user_context
):
    real = SkillService(repository_factory=MagicMock(), user_context=mock_user_context)
    mock_skill_service.create_from_zip.side_effect = real.create_from_zip

    response = await async_client.post(
        "/v1/workspaces/acme/skills/upload",
        files={"file": ("skill.zip", b"this is not a zip archive", "application/zip")},
    )

    assert response.status_code == 400
    assert "not a valid ZIP" in response.json()["detail"]
