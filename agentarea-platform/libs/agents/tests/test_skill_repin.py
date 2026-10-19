"""Installs made before packages existed are repinned to their item's package (ADR-0044).

Such a row holds the stub body its install copied (in ``content``, or moved
into a one-file workspace package), so it reads as edited. When its body is
still exactly what its catalog item gave it, nobody edited it: it is
re-installed from the item's current package, keeping its id. A row whose
body differs is left alone; one whose item is gone is reported.
"""


import pytest
from agentarea_agents.application.skill_packages import clear_package_cache
from agentarea_agents.domain.skill_models import Skill
from agentarea_agents.infrastructure.github_skill_importer import GitHubSourceGoneError
from agentarea_agents.infrastructure.skill_storage_service import package_digest
from agentarea_governance.application.catalog_install import CatalogInstallRefusedError

from .test_catalog_skills import FakeCatalogRepo, _item
from .test_skill_catalog_install import COMMIT, PDF, TREE, StubGitHub, _pointer_item, _service

STUB = "---\nname: pdf\n---\nFill PDFs. https://github.com/owner/repo"


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_package_cache()
    yield
    clear_package_cache()


def _stub_item(**spec):
    return _item(name="pdf", version="3", spec={"source_type": "content", "content": STUB, **spec})


async def _legacy_row(repo, item, **columns) -> Skill:
    skill = await repo.create(
        name="pdf",
        slug="pdf",
        source_type="content",
        registry_item_id=item.id,
        **{"content": STUB, "s3_path": None, **columns},
    )
    skill.workspace_id = "w1"
    return skill


async def test_a_row_still_holding_its_stub_is_repinned_in_place():
    item = _stub_item()
    svc, repo, catalog, s3 = _service(catalog=FakeCatalogRepo([item]))
    skill = await _legacy_row(repo, item)

    result = await svc.repin_from_catalog(skill.id)

    prefix = f"skills/catalog/{package_digest({'SKILL.md': STUB.encode()})}/"
    assert (result.status, result.skill.id) == ("repinned", skill.id)
    assert (skill.s3_path, skill.content) == (prefix, None)
    assert catalog.installed == [(item.id, str(skill.id), "3")]


async def test_a_stub_moved_into_a_workspace_package_is_repinned_and_the_copy_removed():
    item = _stub_item()
    svc, repo, catalog, s3 = _service(catalog=FakeCatalogRepo([item]))
    skill = await _legacy_row(repo, item)
    await svc.packages.move_body_to_package(skill)
    own = f"skills/w1/{skill.id}/"
    assert skill.s3_path == own

    result = await svc.repin_from_catalog(skill.id)

    assert result.status == "repinned"
    assert skill.s3_path.startswith("skills/catalog/")
    assert s3.under(own) == {}


async def test_the_item_moved_to_a_folder_is_repinned_to_that_folder():
    item = _pointer_item()
    item.spec["content"] = STUB
    svc, repo, catalog, s3 = _service(catalog=FakeCatalogRepo([item]))
    skill = await _legacy_row(repo, item)

    result = await svc.repin_from_catalog(skill.id)

    assert result.status == "repinned"
    assert skill.s3_path == f"skills/catalog/{package_digest(PDF)}/"
    assert skill.source_url == f"https://github.com/owner/repo/tree/{COMMIT}/skills/pdf"
    assert catalog.installed == [(item.id, str(skill.id), TREE)]


async def test_a_row_still_reading_the_legacy_package_it_was_installed_with_is_repinned():
    item = _stub_item(s3_path="skills/platform/legacy/")
    svc, repo, _, s3 = _service(catalog=FakeCatalogRepo([item]))
    s3.objects["skills/platform/legacy/SKILL.md"] = b"# Legacy package"
    skill = await _legacy_row(repo, item, content=None, s3_path="skills/platform/legacy/")

    assert (await svc.repin_from_catalog(skill.id)).status == "repinned"


@pytest.mark.parametrize(
    ("columns", "files"),
    [
        ({"content": STUB + "\nmy note"}, None),
        ({"content": None}, {"SKILL.md": STUB.encode(), "extra.md": b"mine"}),
        ({"content": None}, {"SKILL.md": b"# rewritten"}),
    ],
)
async def test_a_row_whose_body_was_edited_is_left_alone(columns, files):
    item = _stub_item()
    svc, repo, catalog, s3 = _service(catalog=FakeCatalogRepo([item]))
    skill = await _legacy_row(repo, item, **columns)
    if files:
        skill.s3_path = await svc.storage_service.store_package_files(str(skill.id), "w1", files)
    before = (skill.s3_path, skill.content)

    result = await svc.repin_from_catalog(skill.id)

    assert result.status == "edited"
    assert (skill.s3_path, skill.content) == before
    assert catalog.installed == []


async def test_a_row_whose_item_no_longer_carries_a_body_to_compare_is_left_alone():
    item = _pointer_item()
    svc, repo, catalog, _ = _service(catalog=FakeCatalogRepo([item]))
    skill = await _legacy_row(repo, item)

    assert (await svc.repin_from_catalog(skill.id)).status == "unverified"
    assert catalog.installed == []


async def test_an_installed_package_is_already_pinned():
    item = _stub_item()
    svc, _, catalog, _ = _service(catalog=FakeCatalogRepo([item]))
    skill = await svc.install_catalog_skill(item.id)
    catalog.installed.clear()

    assert (await svc.repin_from_catalog(skill.id)).status == "pinned"
    assert catalog.installed == []


async def test_a_row_whose_item_is_gone_is_reported_not_deleted():
    item = _stub_item()
    svc, repo, _, _ = _service(catalog=FakeCatalogRepo([]))
    skill = await _legacy_row(repo, item)

    result = await svc.repin_from_catalog(skill.id)

    assert result.status == "gone"
    assert await repo.get_by_id(skill.id) is skill
    assert skill.content == STUB


async def test_an_item_removed_upstream_is_reported_as_gone():
    item = _pointer_item()
    item.spec["content"] = STUB
    svc, repo, _, _ = _service(
        catalog=FakeCatalogRepo([item]), github=StubGitHub(error=GitHubSourceGoneError("gone"))
    )
    skill = await _legacy_row(repo, item)

    result = await svc.repin_from_catalog(skill.id)

    assert result.status == "gone"
    assert skill.content == STUB


async def test_a_dry_run_changes_nothing():
    item = _stub_item()
    svc, repo, catalog, s3 = _service(catalog=FakeCatalogRepo([item]))
    skill = await _legacy_row(repo, item)

    result = await svc.repin_from_catalog(skill.id, dry_run=True)

    assert result.status == "would_repin"
    assert (skill.s3_path, skill.content) == (None, STUB)
    assert catalog.installed == [] and s3.objects == {}


async def test_a_repin_the_policy_refuses_is_reported():
    class Refuse:
        async def require_allowed(self, *, registry_id, trust):
            raise CatalogInstallRefusedError("Install refused by policy: no")

    item = _stub_item()
    svc, repo, catalog, _ = _service(catalog=FakeCatalogRepo([item]))
    svc._install_guard = Refuse()
    skill = await _legacy_row(repo, item)

    result = await svc.repin_from_catalog(skill.id)

    assert (result.status, result.error) == ("refused", "Install refused by policy: no")
    assert skill.content == STUB


async def test_a_skill_not_installed_from_a_catalog_is_not_repinned():
    svc, repo, _, _ = _service()
    skill = await repo.create(name="own", slug="own", source_type="content", content="# own")

    assert (await svc.repin_from_catalog(skill.id)).status == "not_installed"
