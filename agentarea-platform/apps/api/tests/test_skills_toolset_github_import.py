"""Regression tests for GitHub skill import tool behavior."""

import json
from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest
from agentarea_agents.tools import skills_toolset
from agentarea_agents.tools.skills_toolset import SkillsToolset


@pytest.mark.asyncio
async def test_import_from_github_downloads_repo_once_for_multiple_skills(monkeypatch):
    candidates = [
        {"name": "One", "description": None, "package_path": "skills/one", "raw_url": "raw-1"},
        {"name": "Two", "description": None, "package_path": "skills/two", "raw_url": "raw-2"},
    ]
    download_calls: list[str] = []
    package_calls: list[str | None] = []

    async def fake_candidates(_github_url: str):
        return None, "main", candidates

    async def fake_package_zip(repo_zip_data: bytes, *, package_path: str | None):
        assert repo_zip_data == b"repo-zip"
        package_calls.append(package_path)
        return b"skill-zip"

    async def fake_download(self, github_url: str):
        download_calls.append(github_url)
        return b"repo-zip"

    @asynccontextmanager
    async def fake_platform_context():
        yield (
            None,
            SimpleNamespace(user_id="u1", workspace_id="ws-1"),
            object(),
            None,
            None,
        )

    class FakeRepo:
        async def update(self, _skill_id: str, **kwargs):
            return SimpleNamespace(
                id=_skill_id,
                name=kwargs.get("name", "skill"),
                description=None,
                source_type="zip",
                source_url=kwargs.get("source_url"),
            )

    class FakeSkillService:
        def __init__(self, **_kwargs):
            self._counter = 0

        def _get_repository(self):
            return FakeRepo()

        async def create_from_zip(self, **_kwargs):
            self._counter += 1
            return SimpleNamespace(
                id=f"skill-{self._counter}",
                name=f"Skill {self._counter}",
                description=None,
                source_type="zip",
                source_url=None,
            )

    from agentarea_agents.application import skill_service
    from agentarea_agents.infrastructure import github_skill_importer

    monkeypatch.setattr(skills_toolset, "_list_github_skill_candidates", fake_candidates)
    monkeypatch.setattr(skills_toolset, "_github_skill_package_zip", fake_package_zip)
    monkeypatch.setattr(skills_toolset, "platform_context", fake_platform_context)
    monkeypatch.setattr(github_skill_importer.GitHubSkillImporter, "download_repo", fake_download)
    monkeypatch.setattr(skill_service, "SkillService", FakeSkillService)

    result = json.loads(
        await SkillsToolset()._import_github_packages(
            github_url="https://github.com/acme/repo",
            source_url="https://github.com/acme/repo",
            import_all=True,
        )
    )

    assert result["count"] == 2
    assert download_calls == ["https://github.com/acme/repo"]
    assert package_calls == ["skills/one", "skills/two"]


@pytest.mark.asyncio
async def test_import_from_github_rejects_large_import_all_selection(monkeypatch):
    candidates = [
        {"name": f"Skill {idx}", "description": None, "package_path": f"skills/{idx}"}
        for idx in range(skills_toolset.MAX_GITHUB_IMPORTS + 1)
    ]

    async def fake_candidates(_github_url: str):
        return None, "main", candidates

    monkeypatch.setattr(skills_toolset, "_list_github_skill_candidates", fake_candidates)

    result = json.loads(
        await SkillsToolset()._import_github_packages(
            github_url="https://github.com/acme/repo",
            source_url="https://github.com/acme/repo",
            import_all=True,
        )
    )

    assert result["error"].startswith("Refusing to import")
