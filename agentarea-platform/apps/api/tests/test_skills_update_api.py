"""Only a workspace admin moves an installed skill to its catalog item's new version."""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_agents.application.skill_service import (
    SkillCustomizedError,
    SkillNotFromCatalogError,
    SkillService,
    SkillUpdateResult,
)
from agentarea_agents.infrastructure.catalog_skill_repository import CatalogProvenance
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubSourceGoneError,
    GitHubTreeMismatchError,
)
from agentarea_api.api.v1.skills import get_skill_service, router
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.dependencies import get_user_context
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import register_singleton
from agentarea_common.exceptions import register_error_handlers
from fastapi import FastAPI
from fastapi.testclient import TestClient

SKILL_ID = UUID("6d1f3c1e-6b7a-4d43-9c1e-6f1f0a3b2c11")
NOW = datetime(2026, 10, 19, tzinfo=UTC)


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _skill(**over):
    base = {
        "id": SKILL_ID,
        "name": "pdf",
        "slug": "pdf",
        "description": None,
        "source_type": "github",
        "source_url": "https://github.com/o/r/tree/1/pdf",
        "network_scope": "private",
        "workspace_id": "ws-acme",
        "s3_path": f"skills/catalog/{'d' * 64}/",
        "registry_item_id": uuid4(),
        "created_at": NOW,
        "updated_at": NOW,
        "is_catalog": False,
        "update_available": False,
        "catalog_provenance": None,
    }
    return SimpleNamespace(**{**base, **over})


def _client(context: UserContext) -> tuple[TestClient, AsyncMock]:
    service = AsyncMock(spec=SkillService)
    service.user_context = context
    app = FastAPI()
    register_error_handlers(app)
    app.include_router(router, prefix="/v1/workspaces/{workspace}")
    app.dependency_overrides[get_skill_service] = lambda: service
    app.dependency_overrides[get_user_context] = lambda: context
    return TestClient(app), service


def _member() -> UserContext:
    return UserContext(user_id="user-member", workspace_id="ws-acme")


def _admin() -> UserContext:
    return UserContext(user_id="user-owner", workspace_id="ws-acme", admin_workspaces=["ws-acme"])


@pytest.mark.parametrize(
    "path", [f"/v1/workspaces/acme/skills/{SKILL_ID}/update", "/v1/workspaces/acme/skills/update-all"]
)
def test_a_member_cannot_update_installed_skills(path):
    client, service = _client(_member())

    response = client.post(path)

    assert response.status_code == 403, response.text
    assert not service.method_calls


def test_an_admin_updates_one_skill():
    client, service = _client(_admin())
    skill = _skill()
    service.update_from_catalog.return_value = SkillUpdateResult(
        str(SKILL_ID), "pdf", "updated", skill
    )

    response = client.post(f"/v1/workspaces/acme/skills/{SKILL_ID}/update")

    assert response.status_code == 200, response.text
    assert response.json()["id"] == str(SKILL_ID)
    assert response.json()["customized"] is False
    service.update_from_catalog.assert_awaited_once_with(SKILL_ID, discard_changes=False)


def test_updating_a_customized_skill_conflicts_unless_its_changes_are_discarded():
    client, service = _client(_admin())
    service.update_from_catalog.side_effect = SkillCustomizedError("edited")

    refused = client.post(f"/v1/workspaces/acme/skills/{SKILL_ID}/update")

    assert refused.status_code == 409
    assert (refused.json()["code"], refused.json()["detail"]) == ("skill_customized", "edited")
    service.update_from_catalog.side_effect = None
    service.update_from_catalog.return_value = SkillUpdateResult(
        str(SKILL_ID), "pdf", "updated", _skill()
    )
    forced = client.post(f"/v1/workspaces/acme/skills/{SKILL_ID}/update?discard_changes=true")
    assert forced.status_code == 200, forced.text
    service.update_from_catalog.assert_awaited_with(SKILL_ID, discard_changes=True)


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (SkillNotFromCatalogError("not installed"), "skill_not_from_catalog"),
        (GitHubTreeMismatchError("o/r/pdf is another tree"), "skill_tree_mismatch"),
    ],
)
def test_each_update_conflict_says_which_one_it_is(error, code):
    client, service = _client(_admin())
    service.update_from_catalog.side_effect = error

    response = client.post(f"/v1/workspaces/acme/skills/{SKILL_ID}/update")

    assert response.status_code == 409
    assert (response.json()["code"], response.json()["detail"]) == (code, str(error))


def test_a_skill_removed_upstream_is_gone_not_a_server_error():
    client, service = _client(_admin())
    service.update_from_catalog.side_effect = GitHubSourceGoneError(
        "The skill was removed upstream: o/r/pdf is not in o/r"
    )

    response = client.post(f"/v1/workspaces/acme/skills/{SKILL_ID}/update")

    assert response.status_code == 410
    assert "removed upstream" in response.json()["detail"]
    assert response.json()["code"] == "skill_source_gone"


def test_installing_a_skill_removed_upstream_is_gone():
    client, service = _client(_member())
    service.install_catalog_skill.side_effect = GitHubSourceGoneError("removed upstream")

    response = client.post(f"/v1/workspaces/acme/skills/{SKILL_ID}/install")

    assert response.status_code == 410
    assert "removed upstream" in response.json()["detail"]


def test_update_all_reports_every_skill():
    client, service = _client(_admin())
    other = uuid4()
    service.update_all_from_catalog.return_value = [
        SkillUpdateResult(str(SKILL_ID), "pdf", "updated", _skill()),
        SkillUpdateResult(str(other), "docx", "customized", _skill(id=other, name="docx")),
        SkillUpdateResult(str(uuid4()), "gone", "failed", error="removed upstream"),
    ]

    response = client.post("/v1/workspaces/acme/skills/update-all")

    assert response.status_code == 200, response.text
    results = response.json()["results"]
    assert [r["status"] for r in results] == ["updated", "customized", "failed"]
    assert results[0]["skill"]["id"] == str(SKILL_ID)
    assert results[2]["skill"] is None
    assert results[2]["error"] == "removed upstream"


def test_a_skill_response_says_whether_the_workspace_edited_it():
    client, service = _client(_member())
    customized = _skill(
        s3_path=f"skills/ws-acme/{SKILL_ID}/",
        update_available=True,
        catalog_provenance=CatalogProvenance(
            registry_name="acme-skills",
            registry_scope="workspace",
            registry_trust="private",
            removed_upstream=True,
        ),
    )
    service.get_with_catalog.return_value = customized
    service.annotate_installs = AsyncMock()

    from agentarea_common.auth import permission

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(permission, "require_permission", AsyncMock())
        mp.setattr("agentarea_api.api.v1.skills.require_permission", AsyncMock())
        response = client.get(f"/v1/workspaces/acme/skills/{SKILL_ID}")

    assert response.status_code == 200, response.text
    body = response.json()
    assert (body["customized"], body["update_available"]) == (True, True)
    assert (body["registry_name"], body["registry_scope"], body["registry_trust"]) == (
        "acme-skills",
        "workspace",
        "private",
    )
    assert body["removed_upstream"] is True
    service.annotate_installs.assert_awaited_once_with([customized])


@pytest.mark.parametrize(
    "path",
    [
        f"/v1/workspaces/acme/skills/{SKILL_ID}/content",
        f"/v1/workspaces/acme/skills/{SKILL_ID}/files",
        f"/v1/workspaces/acme/skills/{SKILL_ID}/files/SKILL.md",
    ],
)
def test_reading_a_catalog_skill_whose_source_is_gone_is_gone(path):
    client, service = _client(_member())
    service.get_with_catalog.return_value = _skill(is_catalog=True)
    gone = GitHubSourceGoneError("The skill was removed upstream: o/r/pdf")
    service.read_skill_md.side_effect = gone
    service.get_skill_files.side_effect = gone
    service.get_skill_file_url.side_effect = gone

    response = client.get(path)

    assert response.status_code == 410
    assert "removed upstream" in response.json()["detail"]
