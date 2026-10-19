"""Every skill body is read from its package (ADR-0044)."""

import logging
from uuid import uuid4

import pytest
from agentarea_agents.application.skill_packages import SkillPackages, clear_package_cache
from agentarea_agents.domain.skill_models import Skill
from agentarea_agents.infrastructure.github_skill_importer import GitHubFolder
from agentarea_agents.infrastructure.skill_storage_service import package_digest

from .fake_s3 import fake_storage
from .test_catalog_skills import FakeSkillRepo

TREE = "2" * 40
COMMIT = "1" * 40


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_package_cache()
    yield
    clear_package_cache()


class StubGitHub:
    def __init__(self, files):
        self.files = files
        self.calls = []

    async def download_folder(self, repo, path, *, ref, tree_sha):
        self.calls.append((repo, path, ref, tree_sha))
        return GitHubFolder(commit=ref or COMMIT, tree_sha=tree_sha or TREE, files=self.files)


def _tenant(**kw):
    return Skill(id=uuid4(), name="S", slug="s", source_type="content", workspace_id="w1", **kw)


def _packages(repo=None, github=None, s3=None):
    storage, s3 = fake_storage(s3)
    return SkillPackages(storage, github or StubGitHub({}), repo), storage, s3


async def test_the_body_is_read_from_the_package():
    packages, storage, _ = _packages()
    skill = _tenant()
    skill.s3_path = await storage.store_package_files(
        str(skill.id), "w1", {"SKILL.md": b"# From S3", "a.txt": b"a"}
    )

    assert await packages.read_skill_md(skill) == "# From S3"
    assert await packages.read_files(skill) == {"SKILL.md": b"# From S3", "a.txt": b"a"}


async def test_a_catalog_package_is_read_from_storage_once_per_process():
    packages, storage, s3 = _packages()
    skill = _tenant()
    skill.s3_path = await storage.store_catalog_package({"SKILL.md": b"# Catalog"})

    assert await packages.read_skill_md(skill) == "# Catalog"
    reads = len(s3.gets)
    assert await packages.read_skill_md(skill) == "# Catalog"
    assert await packages.read_files(skill) == {"SKILL.md": b"# Catalog"}
    assert len(s3.gets) == reads


async def test_a_tenant_package_is_never_cached():
    packages, storage, s3 = _packages()
    skill = _tenant()
    skill.s3_path = await storage.store_package_files(str(skill.id), "w1", {"SKILL.md": b"v1"})
    assert await packages.read_skill_md(skill) == "v1"

    s3.objects[f"{skill.s3_path}SKILL.md"] = b"v2"

    assert await packages.read_skill_md(skill) == "v2"


async def test_a_row_still_holding_its_body_is_moved_into_a_package_on_first_read(caplog):
    skill = _tenant(content="# Legacy body")
    repo = FakeSkillRepo([skill])
    packages, _, s3 = _packages(repo=repo)

    with caplog.at_level(logging.INFO):
        assert await packages.read_skill_md(skill) == "# Legacy body"

    prefix = f"skills/w1/{skill.id}/"
    assert skill.s3_path == prefix
    assert skill.content is None
    assert s3.under(prefix) == {"SKILL.md": b"# Legacy body"}
    assert any("Moved the body of skill" in r.getMessage() for r in caplog.records)


async def test_a_skill_with_neither_package_nor_body_is_an_error():
    packages, _, _ = _packages(repo=FakeSkillRepo())

    with pytest.raises(ValueError, match="neither a package nor a body"):
        await packages.read_skill_md(_tenant())


async def test_a_package_without_skill_md_is_an_error():
    packages, storage, _ = _packages()
    skill = _tenant()
    skill.s3_path = await storage.store_package_files(str(skill.id), "w1", {"notes.md": b"n"})

    with pytest.raises(ValueError, match=r"no SKILL\.md"):
        await packages.read_skill_md(skill)


def _projection(spec):
    skill = Skill(id=uuid4(), name="Cat", slug="cat", source_type="github")
    skill.is_catalog = True
    skill.catalog_spec = spec
    return skill


async def test_a_catalog_projection_with_an_inline_body_is_stored_by_digest():
    packages, _, s3 = _packages()
    files = {"SKILL.md": b"# Curated"}

    assert await packages.read_skill_md(_projection({"content": "# Curated"})) == "# Curated"
    assert s3.under(f"skills/catalog/{package_digest(files)}/") == files


async def test_a_github_pointer_is_fetched_once_then_read_by_its_tree():
    github = StubGitHub({"SKILL.md": b"---\nname: pdf\n---\n# PDF"})
    packages, _, s3 = _packages(github=github)
    spec = {
        "source": {
            "type": "github",
            "repo": "owner/repo",
            "path": "skills/pdf",
            "ref": COMMIT,
            "tree_sha": TREE,
        }
    }

    assert (await packages.read_skill_md(_projection(spec))).endswith("# PDF")
    clear_package_cache()
    again, _, _ = _packages(github=github, s3=s3)
    assert (await again.read_skill_md(_projection(spec))).endswith("# PDF")

    assert github.calls == [("owner/repo", "skills/pdf", COMMIT, TREE)]


async def test_a_github_folder_without_skill_md_is_refused():
    packages, _, s3 = _packages(github=StubGitHub({"README.md": b"r"}))
    spec = {"source": {"type": "github", "repo": "o/r", "path": "x", "tree_sha": TREE}}

    with pytest.raises(ValueError, match=r"SKILL\.md"):
        await packages.store_catalog_item(spec)
    assert s3.objects == {}
