"""An installed skill changes only when an admin updates it (ADR-0044)."""

from dataclasses import replace
from uuid import UUID

import pytest
from agentarea_agents.application.skill_packages import clear_package_cache
from agentarea_agents.application.skill_service import (
    SkillCustomizedError,
    SkillNotFromCatalogError,
    is_customized,
)
from agentarea_agents.infrastructure.github_skill_importer import (
    GitHubFolder,
    GitHubSourceGoneError,
)
from agentarea_agents.infrastructure.skill_storage_service import package_digest

from .test_catalog_skills import FakeCatalogRepo
from .test_skill_catalog_install import DeletingRepo, _pointer_item, _service

OLD_TREE, NEW_TREE = "a" * 40, "b" * 40
V1 = {"SKILL.md": b"# v1"}
V2 = {"SKILL.md": b"# v2", "new.md": b"n"}


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_package_cache()
    yield
    clear_package_cache()


class InstalledRepo(DeletingRepo):
    async def list_from_catalog(self):
        return [s for s in self._skills if s.registry_item_id is not None]


class TreeGitHub:
    """Serves each tree SHA its own files, as GitHub serves each commit."""

    def __init__(self, trees, error_for=()):
        self.trees = trees
        self.error_for = set(error_for)
        self.calls = []

    async def download_folder(self, repo, path, *, ref, tree_sha):
        self.calls.append(tree_sha)
        if tree_sha in self.error_for:
            raise GitHubSourceGoneError("The skill was removed upstream")
        return GitHubFolder(commit="1" * 40, tree_sha=tree_sha, files=self.trees[tree_sha])


async def _installed(catalog_items, trees=None, error_for=()):
    """Install every item at its old tree, then move the catalog to its current one."""
    github = TreeGitHub(trees or {OLD_TREE: V1, NEW_TREE: V2}, error_for)
    repo = InstalledRepo()
    old_items = [replace(i, version=OLD_TREE, spec=_spec(i, OLD_TREE)) for i in catalog_items]
    svc, repo, catalog, s3 = _service(repo=repo, catalog=FakeCatalogRepo(old_items), github=github)
    skills = [await svc.install_catalog_skill(UUID(i.id)) for i in old_items]
    for skill in skills:
        skill.workspace_id = "w1"
    pins = {item_id: version for item_id, _, version in catalog.installed}
    catalog._items = [
        replace(i, installed_version=pins[i.id], spec=_spec(i, i.version)) for i in catalog_items
    ]
    github.calls.clear()
    return svc, repo, catalog, s3, github, skills


def _spec(item, tree):
    return {**item.spec, "source": {**item.spec["source"], "ref": "1" * 40, "tree_sha": tree}}


async def test_an_update_stores_the_current_version_and_moves_the_pin():
    item = _pointer_item(tree_sha=NEW_TREE)
    svc, _, catalog, s3, github, [skill] = await _installed([item])

    result = await svc.update_from_catalog(skill.id)

    assert result.status == "updated"
    assert github.calls == [NEW_TREE]
    assert result.skill.s3_path == f"skills/catalog/{package_digest(V2)}/"
    assert await svc.read_skill_md(result.skill) == "# v2"
    assert catalog.installed[-1] == (item.id, str(skill.id), NEW_TREE)
    assert s3.under(f"skills/catalog/{package_digest(V1)}/") == V1


async def test_a_skill_already_at_the_current_version_is_left_alone():
    item = _pointer_item(tree_sha=OLD_TREE)
    svc, _, _, _, github, [skill] = await _installed([item])

    result = await svc.update_from_catalog(skill.id)

    assert result.status == "up_to_date"
    assert github.calls == []


async def test_a_customized_skill_is_not_updated_over_its_edit():
    item = _pointer_item(tree_sha=NEW_TREE)
    svc, _, _, _, github, [skill] = await _installed([item])
    edited = await svc.set_content(skill.id, "# my edit")
    edited.workspace_id = "w1"
    assert is_customized(edited)

    with pytest.raises(SkillCustomizedError):
        await svc.update_from_catalog(skill.id)
    assert github.calls == []


async def test_discarding_the_edit_updates_and_keeps_the_edit_to_roll_back_to():
    item = _pointer_item(tree_sha=NEW_TREE)
    svc, repo, _, s3, _, [skill] = await _installed([item])
    edited = await svc.set_content(skill.id, "# my edit")
    own = edited.s3_path
    assert s3.under(own)

    result = await svc.update_from_catalog(skill.id, discard_changes=True)

    assert result.status == "updated"
    assert not is_customized(result.skill)
    assert await svc.read_skill_md(result.skill) == "# v2"
    assert s3.under(own) == {"SKILL.md": b"# my edit"}
    [_, edit, _] = await repo.list_versions(skill.id)
    restored = await svc.rollback(skill.id, edit.id)
    assert await svc.read_skill_md(restored) == "# my edit"


async def test_a_skill_not_installed_from_the_catalog_cannot_be_updated():
    svc, repo, _, _ = _service(repo=InstalledRepo())
    skill = await repo.create(name="Own", slug="own", source_type="content", s3_path="x/")

    with pytest.raises(SkillNotFromCatalogError):
        await svc.update_from_catalog(skill.id)


async def test_update_all_updates_what_it_can_and_reports_each_skill():
    outdated = _pointer_item(tree_sha=NEW_TREE)
    edited = _pointer_item(tree_sha=NEW_TREE)
    current = _pointer_item(tree_sha=OLD_TREE)
    gone = _pointer_item(tree_sha="c" * 40)
    svc, _, catalog, _, _, skills = await _installed(
        [outdated, edited, current, gone],
        trees={OLD_TREE: V1, NEW_TREE: V2},
        error_for={"c" * 40},
    )
    await svc.set_content(skills[1].id, "# my edit")

    results = {r.skill_id: r for r in await svc.update_all_from_catalog()}

    assert {sid: r.status for sid, r in results.items()} == {
        str(skills[0].id): "updated",
        str(skills[1].id): "customized",
        str(skills[3].id): "failed",
    }
    assert "removed upstream" in (results[str(skills[3].id)].error or "")
    assert catalog.installed[-1] == (outdated.id, str(skills[0].id), NEW_TREE)
