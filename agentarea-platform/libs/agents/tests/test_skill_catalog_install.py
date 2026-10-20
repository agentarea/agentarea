"""Installing a catalog skill fetches its real folder and pins it (ADR-0044)."""

from dataclasses import replace
from uuid import UUID

import pytest
from agentarea_agents.application.skill_packages import CatalogMirror, clear_package_cache
from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubFolder,
    GitHubTreeMismatchError,
)
from agentarea_agents.infrastructure.skill_storage_service import package_digest
from agentarea_agents.schemas.skills_dto import SkillCreateFromContent
from agentarea_common.auth.context import UserContext

from .fake_s3 import fake_storage
from .test_catalog_skills import AllowInstalls, FakeCatalogRepo, FakeFactory, FakeSkillRepo, _item

COMMIT = "1" * 40
TREE = "2" * 40
PDF = {"SKILL.md": b"---\nname: pdf\n---\n# PDF", "scripts/fill.py": b"print(1)"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_package_cache()
    yield
    clear_package_cache()


class StubGitHub:
    def __init__(self, files=PDF, error=None):
        self.files = files
        self.error = error
        self.calls = []

    async def download_folder(self, repo, path, *, ref, tree_sha):
        self.calls.append((repo, path, ref, tree_sha))
        if self.error:
            raise self.error
        return GitHubFolder(commit=ref or COMMIT, tree_sha=tree_sha or TREE, files=self.files)


class DeletingRepo(FakeSkillRepo):
    async def delete(self, skill_id):
        self._skills = [s for s in self._skills if str(s.id) != str(skill_id)]
        return True


def _service(repo=None, catalog=None, github=None):
    repo = repo or DeletingRepo()
    catalog = catalog or FakeCatalogRepo()
    storage, s3 = fake_storage()
    uc = UserContext(user_id="u1", workspace_id="w1")
    svc = SkillService(
        FakeFactory(repo, uc),
        uc,
        storage_service=storage,
        github_importer=github or StubGitHub(),
        install_guard=AllowInstalls(),
    )
    svc._get_repository = lambda: repo
    svc._get_catalog_repository = lambda: catalog
    return svc, repo, catalog, s3


def _pointer_item(ref=COMMIT, tree_sha=TREE, version=None):
    source = {"type": "github", "repo": "owner/repo", "path": "skills/pdf"}
    if ref:
        source["ref"] = ref
    if tree_sha:
        source["tree_sha"] = tree_sha
    return _item(
        name="pdf--owner-repo",
        version=version or tree_sha or "latest",
        spec={
            "source_type": "github",
            "source": source,
            "source_url": "https://github.com/owner/repo/tree/HEAD/skills/pdf",
        },
    )


async def test_install_downloads_the_pinned_folder_and_stores_it_by_digest():
    github = StubGitHub()
    item = _pointer_item()
    svc, repo, catalog, s3 = _service(catalog=FakeCatalogRepo([item]), github=github)

    skill = await svc.install_catalog_skill(UUID(item.id))

    prefix = f"skills/catalog/{package_digest(PDF)}/"
    assert github.calls == [("owner/repo", "skills/pdf", COMMIT, TREE)]
    assert s3.under(prefix) == PDF
    created = repo.created_kwargs[0]
    assert created["s3_path"] == prefix
    assert created["content"] is None
    assert created["registry_item_id"] == item.id
    assert created["source_url"] == f"https://github.com/owner/repo/tree/{COMMIT}/skills/pdf"
    assert catalog.installed == [(item.id, str(skill.id), TREE)]
    assert await svc.read_skill_md(skill) == PDF["SKILL.md"].decode()


async def test_install_without_a_ref_pins_the_resolved_commit():
    item = _pointer_item(ref=None, tree_sha=None)
    svc, repo, catalog, _ = _service(catalog=FakeCatalogRepo([item]))

    skill = await svc.install_catalog_skill(UUID(item.id))

    assert skill.source_url == f"https://github.com/owner/repo/tree/{COMMIT}/skills/pdf"
    # The pin is the tree that was fetched, not the index's "latest".
    assert catalog.installed == [(item.id, str(skill.id), TREE)]


async def test_a_folder_that_is_not_the_pinned_tree_installs_nothing():
    item = _pointer_item()
    github = StubGitHub(error=GitHubTreeMismatchError("moved"))
    svc, repo, catalog, s3 = _service(catalog=FakeCatalogRepo([item]), github=github)

    with pytest.raises(GitHubTreeMismatchError):
        await svc.install_catalog_skill(UUID(item.id))

    assert repo.created_kwargs == []
    assert catalog.installed == []
    assert s3.objects == {}


async def test_an_inline_catalog_skill_installs_as_a_one_file_package():
    item = _item(spec={"source_type": "content", "content": "# Curated"}, version="3")
    svc, repo, catalog, s3 = _service(catalog=FakeCatalogRepo([item]))

    skill = await svc.install_catalog_skill(UUID(item.id))

    prefix = f"skills/catalog/{package_digest({'SKILL.md': b'# Curated'})}/"
    assert skill.s3_path == prefix
    assert skill.content is None
    assert s3.under(prefix) == {"SKILL.md": b"# Curated"}
    assert catalog.installed == [(item.id, str(skill.id), "3")]


async def test_create_from_content_writes_a_one_file_package_not_the_column():
    svc, repo, _, s3 = _service()

    skill = await svc.create_from_content(SkillCreateFromContent(content="# Mine\nbody"))

    files = {"SKILL.md": b"# Mine\nbody"}
    prefix = f"skills/w1/packages/{package_digest(files)}/"
    assert skill.s3_path == prefix
    assert skill.content is None
    assert repo.created_kwargs[0]["content"] is None
    assert s3.under(prefix) == files
    assert [v.reason for v in await repo.list_versions(skill.id)] == ["create"]


async def test_editing_an_installed_skill_copies_it_and_leaves_the_catalog_package_alone():
    item = _pointer_item()
    svc, _, _, s3 = _service(catalog=FakeCatalogRepo([item]))
    skill = await svc.install_catalog_skill(UUID(item.id))
    catalog_prefix = skill.s3_path

    edited = await svc.set_content(skill.id, "# Edited")

    files = {**PDF, "SKILL.md": b"# Edited"}
    own = f"skills/w1/packages/{package_digest(files)}/"
    assert edited.s3_path == own
    assert edited.content is None
    assert s3.under(own) == files
    assert s3.under(catalog_prefix) == PDF


async def test_deleting_an_installed_skill_keeps_the_shared_package():
    item = _pointer_item()
    svc, _, _, s3 = _service(catalog=FakeCatalogRepo([item]))
    skill = await svc.install_catalog_skill(UUID(item.id))

    assert await svc.delete(skill.id)
    assert s3.under(skill.s3_path) == PDF


async def test_listing_the_files_of_a_pre_package_row_moves_its_body():
    svc, repo, _, s3 = _service()
    skill = await repo.create(
        name="Old", slug="old", source_type="content", content="# Old", s3_path=None
    )
    skill.workspace_id = "w1"

    files = await svc.get_skill_files(skill.id)

    assert [(f.path, f.size) for f in files] == [("SKILL.md", 5)]
    assert skill.s3_path == f"skills/w1/packages/{package_digest({'SKILL.md': b'# Old'})}/"
    assert skill.content is None


class OfflineGitHub(StubGitHub):
    async def download_folder(self, repo, path, *, ref, tree_sha):
        raise AssertionError("a mirrored item is installed without GitHub")


async def test_a_mirrored_item_installs_from_the_package_its_sync_stored():
    storage, s3 = fake_storage()
    mirror = CatalogMirror(storage, StubGitHub(), workspace_id=None)
    item = _pointer_item()
    item.spec["package"] = await mirror(item.spec)
    svc, repo, catalog, _ = _service(catalog=FakeCatalogRepo([item]), github=OfflineGitHub())
    svc._storage_service = storage

    skill = await svc.install_catalog_skill(UUID(item.id))

    assert skill.s3_path == f"skills/catalog/{package_digest(PDF)}/"
    assert skill.source_url == f"https://github.com/owner/repo/tree/{COMMIT}/skills/pdf"
    assert catalog.installed == [(item.id, str(skill.id), TREE)]
    assert await svc.read_skill_md(skill) == PDF["SKILL.md"].decode()


async def test_a_workspace_registrys_item_installs_into_that_workspaces_store():
    item = replace(_pointer_item(), registry_workspace_id="w1")
    svc, _, _, s3 = _service(catalog=FakeCatalogRepo([item]))

    skill = await svc.install_catalog_skill(UUID(item.id))

    assert skill.s3_path == f"skills/w1/catalog/{package_digest(PDF)}/"
    assert s3.under("skills/catalog/") == {}
