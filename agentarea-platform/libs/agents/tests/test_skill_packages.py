"""Every skill body is read from its package (ADR-0044)."""

import logging
from datetime import datetime
from uuid import uuid4

import pytest
from agentarea_agents.application.skill_packages import (
    CatalogMirror,
    SkillPackages,
    clear_package_cache,
)
from agentarea_agents.domain.skill_models import Skill
from agentarea_agents.infrastructure.github_skill_importer import GitHubFolder, GitHubRateLimitError
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
    skill.s3_path = await storage.store_workspace_package(
        {"SKILL.md": b"# From S3", "a.txt": b"a"}, "w1"
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


async def test_a_workspace_package_is_read_from_storage_once_per_process():
    packages, storage, s3 = _packages()
    skill = _tenant()
    skill.s3_path = await storage.store_workspace_package({"SKILL.md": b"# Own"}, "w1")

    assert await packages.read_skill_md(skill) == "# Own"
    reads = len(s3.gets)
    assert await packages.read_files(skill) == {"SKILL.md": b"# Own"}
    assert len(s3.gets) == reads


async def test_a_pre_package_copy_read_without_a_repository_is_read_in_place_uncached():
    packages, _, s3 = _packages()
    skill = _tenant(s3_path=None)
    skill.s3_path = f"skills/w1/{skill.id}/"
    s3.objects[f"{skill.s3_path}SKILL.md"] = b"v1"
    assert await packages.read_skill_md(skill) == "v1"

    s3.objects[f"{skill.s3_path}SKILL.md"] = b"v2"

    assert await packages.read_skill_md(skill) == "v2"


async def test_a_pre_package_copy_is_moved_into_a_package_on_first_read(caplog):
    skill = _tenant()
    skill.s3_path = f"skills/w1/{skill.id}/"
    repo = FakeSkillRepo([skill])
    packages, _, s3 = _packages(repo=repo)
    s3.objects[f"skills/w1/{skill.id}/SKILL.md"] = b"# Mine"
    s3.objects[f"skills/w1/{skill.id}/notes.md"] = b"n"

    with caplog.at_level(logging.INFO):
        assert await packages.read_skill_md(skill) == "# Mine"

    files = {"SKILL.md": b"# Mine", "notes.md": b"n"}
    assert skill.s3_path == f"skills/w1/packages/{package_digest(files)}/"
    assert s3.under(skill.s3_path) == files
    # The copy stays until the explicit clean-up command.
    assert s3.under(f"skills/w1/{skill.id}/") == files
    assert [(v.reason, v.s3_path) for v in repo.versions] == [("migrate", skill.s3_path)]
    assert any("Moved the copy" in r.getMessage() for r in caplog.records)


async def test_a_row_still_holding_its_body_is_moved_into_a_package_on_first_read(caplog):
    skill = _tenant(content="# Legacy body")
    repo = FakeSkillRepo([skill])
    packages, _, s3 = _packages(repo=repo)

    with caplog.at_level(logging.INFO):
        assert await packages.read_skill_md(skill) == "# Legacy body"

    prefix = f"skills/w1/packages/{package_digest({'SKILL.md': b'# Legacy body'})}/"
    assert skill.s3_path == prefix
    assert skill.content is None
    assert s3.under(prefix) == {"SKILL.md": b"# Legacy body"}
    assert [v.reason for v in repo.versions] == ["migrate"]
    assert any("Moved the body of skill" in r.getMessage() for r in caplog.records)


async def test_an_edit_left_in_the_row_of_a_packaged_skill_wins_on_first_read():
    # Before packages, editing an imported skill wrote only skills.content,
    # and the prompt read it; the package still holds the import.
    repo = FakeSkillRepo()
    packages, storage, s3 = _packages(repo=repo)
    shared = await storage.store_catalog_package({"SKILL.md": b"# Imported", "fill.py": b"x"})
    skill = _tenant(content="# Edited", s3_path=shared)
    repo._skills = [skill]

    assert await packages.read_skill_md(skill) == "# Edited"

    edited = {"SKILL.md": b"# Edited", "fill.py": b"x"}
    assert (skill.s3_path, skill.content) == (f"skills/w1/packages/{package_digest(edited)}/", None)
    assert s3.under(skill.s3_path) == edited
    assert s3.under(shared) == {"SKILL.md": b"# Imported", "fill.py": b"x"}


async def test_a_skill_with_neither_package_nor_body_is_an_error():
    packages, _, _ = _packages(repo=FakeSkillRepo())

    with pytest.raises(ValueError, match="neither a package nor a body"):
        await packages.read_skill_md(_tenant())


async def test_a_package_without_skill_md_is_an_error():
    packages, storage, _ = _packages()
    skill = _tenant()
    skill.s3_path = await storage.store_workspace_package({"notes.md": b"n"}, "w1")

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


MIRRORED = f"skills/catalog/{'a' * 64}/"


async def test_a_mirrored_item_is_read_from_its_stored_package_without_github():
    github = StubGitHub({"SKILL.md": b"# unused"})
    packages, _, _ = _packages(github=github)
    spec = {
        "source": {"type": "github", "repo": "o/r", "path": "x", "ref": COMMIT, "tree_sha": TREE},
        "package": {"s3_path": MIRRORED, "source_url": "https://github.com/o/r/tree/c/x"},
    }

    package = await packages.store_catalog_item(spec)

    assert (package.s3_path, package.source_url) == (MIRRORED, "https://github.com/o/r/tree/c/x")
    assert github.calls == []


@pytest.mark.parametrize(
    ("s3_path", "workspace_id"),
    [
        (f"skills/ws-2/catalog/{'a' * 64}/", "ws-1"),
        (f"skills/ws-1/catalog/{'a' * 64}/", None),
        (MIRRORED, "ws-1"),
        ("skills/ws-1/some-skill/", "ws-1"),
    ],
)
async def test_a_mirrored_package_outside_its_registrys_store_is_refused(s3_path, workspace_id):
    packages, _, _ = _packages()

    with pytest.raises(ValueError, match="outside"):
        await packages.store_catalog_item(
            {"content": "# x", "package": {"s3_path": s3_path}}, workspace_id=workspace_id
        )


async def test_a_workspace_registrys_item_is_stored_and_aliased_in_that_workspace():
    github = StubGitHub({"SKILL.md": b"---\nname: p\n---\n# Private"})
    packages, storage, s3 = _packages(github=github)
    spec = {
        "source": {"type": "github", "repo": "o/r", "path": "x", "ref": COMMIT, "tree_sha": TREE}
    }

    private = await packages.store_catalog_item(spec, workspace_id="ws-1")
    public = await packages.store_catalog_item(spec)

    assert private.s3_path.startswith("skills/ws-1/catalog/")
    assert public.s3_path.startswith("skills/catalog/")
    # The shared store never answers for a workspace's tree, nor the other way round.
    assert len(github.calls) == 2
    assert await storage.get_github_tree_package(TREE, workspace_id="ws-1") == private.s3_path
    inline = await packages.store_catalog_item({"content": "# Inline"}, workspace_id="ws-1")
    assert inline.s3_path.startswith("skills/ws-1/catalog/")


async def test_the_mirror_stores_each_item_and_says_where():
    github = StubGitHub({"SKILL.md": b"---\nname: p\n---\n# P"})
    storage, s3 = fake_storage()
    mirror = CatalogMirror(storage, github, workspace_id="ws-1")
    spec = {
        "source": {"type": "github", "repo": "o/r", "path": "x", "ref": COMMIT, "tree_sha": TREE}
    }

    package = await mirror(spec)

    assert package["s3_path"].startswith("skills/ws-1/catalog/")
    assert s3.under(package["s3_path"]) == {"SKILL.md": b"---\nname: p\n---\n# P"}
    assert package["source_url"] == f"https://github.com/o/r/tree/{COMMIT}/x"
    assert await mirror({"content": "# Inline"}) == {
        "s3_path": f"skills/ws-1/catalog/{package_digest({'SKILL.md': b'# Inline'})}/",
        "source_url": None,
    }


async def test_the_mirror_stops_asking_github_once_it_is_rate_limited():
    class Limited(StubGitHub):
        async def download_folder(self, repo, path, *, ref, tree_sha):
            self.calls.append(path)
            raise GitHubRateLimitError("rate limited")

    github = Limited({})
    storage, _ = fake_storage()
    mirror = CatalogMirror(storage, github, workspace_id=None)

    for folder in ("a", "b"):
        spec = {"source": {"type": "github", "repo": "o/r", "path": folder, "ref": COMMIT}}
        with pytest.raises(GitHubRateLimitError):
            await mirror(spec)
    assert await mirror({"content": "# Inline"})
    assert github.calls == ["a"]


async def test_previews_of_an_unpinned_pointer_ask_github_once_within_the_ttl(monkeypatch):
    # The live community index has no tree SHAs: every preview of an
    # uninstalled item cost two API calls of a budget all tenants share.
    from agentarea_agents.application import skill_packages

    clock = [1000.0]
    monkeypatch.setattr(skill_packages.time, "monotonic", lambda: clock[0])
    github = StubGitHub({"SKILL.md": b"---\nname: pdf\n---\n# PDF"})
    packages, _, _ = _packages(github=github)
    spec = {"source": {"type": "github", "repo": "o/r", "path": "pdf"}}

    for _ in range(3):
        assert (await packages.read_skill_md(_projection(spec))).endswith("# PDF")
    assert len(github.calls) == 1

    clock[0] += skill_packages.GITHUB_HEAD_TTL_SECONDS + 1
    await packages.read_skill_md(_projection(spec))
    assert len(github.calls) == 2


async def test_the_github_package_caches_are_bounded(monkeypatch):
    from agentarea_agents.application import skill_packages

    monkeypatch.setattr(skill_packages, "GITHUB_CACHE_MAX_ENTRIES", 2)
    packages, _, _ = _packages(github=StubGitHub({"SKILL.md": b"---\nname: p\n---\n# P"}))

    for folder in ("a", "b", "c"):
        await packages.store_catalog_item(
            {"source": {"type": "github", "repo": "o/r", "path": folder}}
        )

    assert len(skill_packages._github_heads) == 2
    assert len(skill_packages._github_trees) <= 2


@pytest.mark.parametrize(
    ("s3_path", "workspace_id"),
    [("skills/ws-2/secret-skill/", None), ("skills/ws-2/secret-skill/", "ws-1"), ("../x/", None)],
)
async def test_a_legacy_package_outside_the_items_area_is_refused(s3_path, workspace_id):
    # Nothing an index publishes sets spec.s3_path today; a later parser
    # change must still not let an item read another tenant's prefix.
    from agentarea_agents.application.skill_service import _project_catalog_skill
    from agentarea_agents.infrastructure.catalog_skill_repository import CatalogSkillItem

    packages, _, _ = _packages()
    item = CatalogSkillItem(
        id=str(uuid4()),
        name="x",
        description=None,
        version=None,
        spec={"s3_path": s3_path},
        installed_entity_id=None,
        installed_version=None,
        created_at=datetime.now(),
        updated_at=datetime.now(),
        registry_workspace_id=workspace_id,
    )

    assert _project_catalog_skill(item).s3_path is None
    with pytest.raises(ValueError, match="outside"):
        await packages.store_catalog_item({"s3_path": s3_path}, workspace_id=workspace_id)


async def test_a_run_reads_the_package_it_was_configured_with():
    # The skill moved to v2 since the run started; the run keeps reading v1.
    packages, storage, _ = _packages()
    v1 = await storage.store_catalog_package({"SKILL.md": b"# v1"})
    v2 = await storage.store_catalog_package({"SKILL.md": b"# v2"})
    skill = _tenant(s3_path=v2)

    assert await packages.read_skill_md(skill, at=v1) == "# v1"
    assert await packages.read_files(skill, at=v1) == {"SKILL.md": b"# v1"}
    assert await packages.read_skill_md(skill) == "# v2"


@pytest.mark.parametrize(
    "foreign",
    ["skills/other-workspace/abc/", "skills/catalog/../w2/x/", "elsewhere/abc/"],
)
async def test_a_pinned_package_outside_the_skills_reach_is_refused(foreign):
    packages, storage, _ = _packages()
    skill = _tenant(s3_path=await storage.store_catalog_package({"SKILL.md": b"# v1"}))

    with pytest.raises(ValueError, match="cannot be read from package"):
        await packages.read_skill_md(skill, at=foreign)
