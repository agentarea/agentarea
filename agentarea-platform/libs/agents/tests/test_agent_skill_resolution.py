"""Attaching a catalog skill to an agent installs it into the workspace first.

Presets name catalog skills, and the create form passes their catalog ids
straight through; the agent must end up with the workspace's own copy.
"""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_agents.application import agent_service as module
from agentarea_agents.application.agent_service import AgentService
from agentarea_common.auth.context import UserContext
from agentarea_common.exceptions.errors import NotFoundError


def _service(workspace_skills: set, catalog: dict) -> AgentService:
    skills_repo = MagicMock()
    skills_repo.get_by_id = AsyncMock(side_effect=lambda sid: object() if sid in workspace_skills else None)
    factory = MagicMock()
    factory.create_repository.return_value = skills_repo
    factory.user_context = UserContext(user_id="user-a", workspace_id="ws-a")
    service = object.__new__(AgentService)
    service.repository_factory = factory
    service._user_context = factory.user_context
    installer = MagicMock()
    installer.install_catalog_skill = AsyncMock(side_effect=lambda sid: catalog.get(sid))
    return service, installer


@pytest.fixture
def patched(monkeypatch):
    def install(installer):
        monkeypatch.setattr(module, "SkillService", lambda *_a, **_k: installer)

    return install


async def test_workspace_skill_is_attached_as_is(patched):
    own = uuid4()
    service, installer = _service({own}, {})
    patched(installer)

    assert await service._resolve_skills([own]) == [own]
    installer.install_catalog_skill.assert_not_awaited()


async def test_catalog_skill_is_installed_and_its_copy_attached(patched):
    catalog_id, copy_id = uuid4(), uuid4()
    service, installer = _service(set(), {catalog_id: SimpleNamespace(id=copy_id)})
    patched(installer)

    assert await service._resolve_skills([catalog_id]) == [copy_id]


async def test_unknown_skill_is_refused(patched):
    service, installer = _service(set(), {})
    patched(installer)

    with pytest.raises(NotFoundError):
        await service._resolve_skills([uuid4()])
