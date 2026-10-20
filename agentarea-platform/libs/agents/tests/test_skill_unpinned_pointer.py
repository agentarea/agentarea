"""A catalog pointer without a tree SHA is pinned to the tree an install fetched (ADR-0044).

Its index version is ``latest``. Recording that as the install's pin made the
install equal to every later version of the folder, so an update was never
shown. The install records the fetched folder's tree SHA instead, and an update
moves the pin to the tree it fetches then.
"""

from dataclasses import replace
from uuid import UUID

import pytest
from agentarea_agents.application.skill_packages import CatalogMirror, clear_package_cache
from agentarea_agents.infrastructure.github_skill_importer import GitHubFolder

from .fake_s3 import fake_storage
from .test_catalog_skills import FakeCatalogRepo
from .test_skill_catalog_install import _pointer_item, _service

OLD_TREE, NEW_TREE = "a" * 40, "b" * 40


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_package_cache()
    yield
    clear_package_cache()


class BranchHead:
    """The folder at the branch head: whatever tree it holds now."""

    def __init__(self, tree: str):
        self.tree = tree
        self.calls = []

    async def download_folder(self, repo, path, *, ref, tree_sha):
        self.calls.append((ref, tree_sha))
        body = f"---\nname: pdf\n---\n# {self.tree[:1]}".encode()
        return GitHubFolder(commit="1" * 40, tree_sha=self.tree, files={"SKILL.md": body})


async def test_an_install_pins_the_tree_it_fetched_not_latest():
    item = _pointer_item(ref=None, tree_sha=None)
    assert item.version == "latest"
    github = BranchHead(OLD_TREE)
    svc, _, catalog, _ = _service(catalog=FakeCatalogRepo([item]), github=github)

    skill = await svc.install_catalog_skill(UUID(item.id))

    assert catalog.installed == [(item.id, str(skill.id), OLD_TREE)]
    assert github.calls == [(None, None)]


async def test_a_new_tree_upstream_is_an_update_and_updating_pins_it():
    item = _pointer_item(ref=None, tree_sha=None)
    github = BranchHead(OLD_TREE)
    svc, _, catalog, _ = _service(catalog=FakeCatalogRepo([item]), github=github)
    skill = await svc.install_catalog_skill(UUID(item.id))
    clear_package_cache()

    # The registry sync found the folder at a new tree and keeps it as the version.
    github.tree = NEW_TREE
    catalog._items = [replace(item, version=NEW_TREE, installed_version=OLD_TREE)]
    await svc.annotate_installs([skill])
    assert skill.update_available is True

    result = await svc.update_from_catalog(skill.id)

    assert result.status == "updated"
    assert catalog.installed[-1] == (item.id, str(skill.id), NEW_TREE)
    assert await svc.read_skill_md(result.skill) == "---\nname: pdf\n---\n# b"


async def test_an_install_at_the_current_tree_is_up_to_date():
    item = _pointer_item(ref=None, tree_sha=None)
    svc, _, catalog, _ = _service(catalog=FakeCatalogRepo([item]), github=BranchHead(OLD_TREE))
    skill = await svc.install_catalog_skill(UUID(item.id))

    catalog._items = [replace(item, version=OLD_TREE, installed_version=OLD_TREE)]
    await svc.annotate_installs([skill])

    assert not getattr(skill, "update_available", False)
    assert (await svc.update_from_catalog(skill.id)).status == "up_to_date"


async def test_a_mirror_records_the_tree_it_stored():
    storage, _ = fake_storage()
    mirror = CatalogMirror(storage, BranchHead(OLD_TREE), workspace_id=None)

    stored = await mirror({"source": {"type": "github", "repo": "o/r", "path": "pdf"}})

    assert stored["tree_sha"] == OLD_TREE
