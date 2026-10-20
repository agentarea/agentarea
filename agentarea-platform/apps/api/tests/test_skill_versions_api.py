"""A skill's versions are listed oldest first, and a rollback points it at one of them."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from agentarea_agents.application.skill_service import SkillVersionNotFoundError
from agentarea_agents.domain.skill_models import SkillVersion
from agentarea_common.auth.permission import PermissionService
from agentarea_common.di.container import get_container

from .test_skills_update_api import SKILL_ID, _authz, _client, _member, _skill  # noqa: F401

NOW = datetime(2026, 10, 20, tzinfo=UTC)


class _Permissions(PermissionService):
    def __init__(self) -> None:
        self.checked: list[tuple[str, str, str]] = []

    async def check(self, user_id, permission, resource_type, resource_id) -> bool:
        self.checked.append((permission, resource_type, resource_id))
        return True


@pytest.fixture(autouse=True)
def permissions():
    container = get_container()
    saved = dict(container._singletons)
    recorder = _Permissions()
    container.register_singleton(PermissionService, recorder)
    yield recorder
    container._singletons.clear()
    container._singletons.update(saved)


def _version(path: str, reason: str) -> SkillVersion:
    return SkillVersion(
        id=uuid4(),
        skill_id=SKILL_ID,
        s3_path=path,
        digest=path.rstrip("/").rsplit("/", 1)[-1],
        reason=reason,
        workspace_id="ws-acme",
        created_by="user-member",
        created_at=NOW,
        updated_at=NOW,
    )


def test_versions_are_listed_and_the_one_the_skill_points_at_is_current(permissions):
    client, service = _client(_member())
    old = _version(f"skills/ws-acme/packages/{'a' * 64}/", "create")
    new = _version(f"skills/ws-acme/packages/{'b' * 64}/", "edit")
    service.get.return_value = _skill(s3_path=new.s3_path, registry_item_id=None)
    service.list_versions.return_value = [old, new]

    response = client.get(f"/v1/workspaces/acme/skills/{SKILL_ID}/versions")

    assert response.status_code == 200, response.text
    assert [(v["reason"], v["digest"], v["current"]) for v in response.json()] == [
        ("create", "a" * 64, False),
        ("edit", "b" * 64, True),
    ]
    assert permissions.checked == [("read", "skill", str(SKILL_ID))]


def test_a_rollback_answers_the_skill_at_that_version(permissions):
    client, service = _client(_member())
    version_id = uuid4()
    service.rollback.return_value = _skill(registry_item_id=None)

    response = client.post(f"/v1/workspaces/acme/skills/{SKILL_ID}/versions/{version_id}/rollback")

    assert response.status_code == 200, response.text
    service.rollback.assert_awaited_once_with(SKILL_ID, version_id)
    assert permissions.checked == [("edit", "skill", str(SKILL_ID))]


def test_a_rollback_to_a_version_the_skill_never_had_is_not_found():
    client, service = _client(_member())
    service.rollback.side_effect = SkillVersionNotFoundError("no such version")

    response = client.post(f"/v1/workspaces/acme/skills/{SKILL_ID}/versions/{uuid4()}/rollback")

    assert response.status_code == 404
    assert response.json()["detail"] == "Skill version not found"
