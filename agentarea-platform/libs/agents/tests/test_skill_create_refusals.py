"""A skill create that is refused leaves nothing behind.

A ZIP whose paths or size the package limits refuse, a file that is not a ZIP,
or a SKILL.md whose name does not fit the ``skills.name`` column must be
refused before the row exists. A create that still fails after the row exists
(the object store, say) removes the row and whatever part of the package it
stored.
"""

import io
import zipfile
from unittest.mock import MagicMock, patch

import pytest

from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.infrastructure.skill_storage_service import SkillStorageService
from agentarea_agents.schemas.skills_dto import SkillCreateFromContent
from agentarea_common.auth.context import UserContext

from .test_catalog_skills import FakeFactory, FakeSkillRepo


class DeletingSkillRepo(FakeSkillRepo):
    def __init__(self):
        super().__init__()
        self.deleted: list[str] = []

    async def delete(self, skill_id):
        self.deleted.append(str(skill_id))
        self._skills = [s for s in self._skills if str(s.id) != str(skill_id)]
        return True


@pytest.fixture
def s3_client():
    client = MagicMock()
    settings = MagicMock()
    settings.ARTIFACTS_BUCKET = "test-bucket"
    with (
        patch(
            "agentarea_agents.infrastructure.skill_storage_service.get_s3_client",
            return_value=client,
        ),
        patch(
            "agentarea_agents.infrastructure.skill_storage_service.get_aws_settings",
            return_value=settings,
        ),
    ):
        yield client


@pytest.fixture
def repo() -> DeletingSkillRepo:
    return DeletingSkillRepo()


def _service(repo: DeletingSkillRepo) -> SkillService:
    uc = UserContext(user_id="u1", workspace_id="w1")
    svc = SkillService(FakeFactory(repo, uc), uc, storage_service=SkillStorageService())
    svc._get_repository = lambda: repo
    return svc


def _zip(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as zf:
        for path, text in entries.items():
            zf.writestr(path, text)
    return buffer.getvalue()


async def test_a_zip_with_a_path_the_package_refuses_creates_no_skill(repo, s3_client):
    data = _zip({"a\\b.txt": "x", "SKILL.md": "---\nname: ghost\n---\nhi"})

    with pytest.raises(ValueError, match="Invalid skill file path"):
        await _service(repo).create_from_zip(data)

    assert await repo.list_all() == []
    assert repo.created_kwargs == []
    s3_client.put_object.assert_not_called()


async def test_a_zip_over_the_package_budget_creates_no_skill(repo, s3_client, monkeypatch):
    from agentarea_agents.application import skill_package_limits as limits

    monkeypatch.setattr(limits, "MAX_PACKAGE_FILES", 1)
    data = _zip({"SKILL.md": "---\nname: big\n---\nhi", "notes.md": "x"})

    with pytest.raises(ValueError, match="more than 1 files"):
        await _service(repo).create_from_zip(data)

    assert repo.created_kwargs == []
    s3_client.put_object.assert_not_called()


async def test_a_file_that_is_not_a_zip_is_refused_as_a_value_error(repo, s3_client):
    with pytest.raises(ValueError, match="not a valid ZIP"):
        await _service(repo).create_from_zip(b"definitely not a zip archive")

    assert repo.created_kwargs == []


@pytest.mark.parametrize("source", ["frontmatter", "heading"])
async def test_a_skill_name_longer_than_its_column_is_refused(repo, s3_client, source):
    long_name = "n" * 300
    content = (
        f"---\nname: {long_name}\n---\nbody"
        if source == "frontmatter"
        else f"# {long_name}\n\nbody"
    )

    with pytest.raises(ValueError, match="255"):
        await _service(repo).create_from_content(SkillCreateFromContent(content=content))
    with pytest.raises(ValueError, match="255"):
        await _service(repo).create_from_zip(_zip({"SKILL.md": content}))

    assert repo.created_kwargs == []
    s3_client.put_object.assert_not_called()


async def test_a_name_override_that_fits_wins_over_a_long_parsed_name(repo, s3_client):
    content = f"---\nname: {'n' * 300}\n---\nbody"

    skill = await _service(repo).create_from_content(
        SkillCreateFromContent(content=content, name="short")
    )

    assert skill.name == "short"


async def test_a_store_failure_after_the_row_exists_removes_the_row(repo, s3_client):
    s3_client.put_object.side_effect = [None, RuntimeError("object store is down")]
    data = _zip({"SKILL.md": "---\nname: half\n---\nhi", "notes.md": "x"})
    service = _service(repo)

    with pytest.raises(RuntimeError, match="object store is down"):
        await service.create_from_zip(data)

    assert len(repo.created_kwargs) == 1
    assert await repo.list_all() == []
    assert len(repo.deleted) == 1
    # The part of the package that did land is listed for deletion under its prefix.
    prefix = service.storage_service._get_s3_prefix("w1", repo.deleted[0])
    s3_client.get_paginator.return_value.paginate.assert_called_with(
        Bucket="test-bucket", Prefix=prefix
    )


async def test_a_valid_zip_still_creates_the_skill_with_its_package(repo, s3_client):
    data = _zip({"SKILL.md": "---\nname: fine\n---\nhi", "scripts/run.sh": "echo"})

    skill = await _service(repo).create_from_zip(data)

    assert skill.name == "fine"
    assert skill.s3_path == f"skills/w1/{skill.id}/"
    keys = {call.kwargs["Key"] for call in s3_client.put_object.call_args_list}
    assert keys == {f"skills/w1/{skill.id}/SKILL.md", f"skills/w1/{skill.id}/scripts/run.sh"}
