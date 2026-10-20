"""A workspace's own skill is a chain of immutable packages, so it has history (ADR-0044).

Authoring, uploading or editing a skill stores its files as a package keyed by
their digest under the workspace's prefix and moves the skill's pointer there;
nothing is ever rewritten in place. Every move is a version, and rolling back
points the skill at an earlier version's package again.
"""

from uuid import UUID, uuid4

import pytest
from agentarea_agents.application.skill_packages import clear_package_cache
from agentarea_agents.application.skill_service import (
    SkillVersionNotFoundError,
    is_customized,
)
from agentarea_agents.infrastructure.skill_storage_service import package_digest
from agentarea_agents.schemas.skills_dto import SkillCreateFromContent

from .test_catalog_skills import FakeCatalogRepo
from .test_skill_catalog_install import PDF, _pointer_item, _service


@pytest.fixture(autouse=True)
def _fresh_cache():
    clear_package_cache()
    yield
    clear_package_cache()


def _own(files: dict[str, bytes]) -> str:
    return f"skills/w1/packages/{package_digest(files)}/"


async def test_every_edit_is_a_new_package_and_a_new_version():
    svc, repo, _, s3 = _service()
    skill = await svc.create_from_content(SkillCreateFromContent(content="# v1"))
    skill.workspace_id = "w1"

    await svc.set_content(skill.id, "# v2")
    await svc.replace_package_from_files(skill.id, {"SKILL.md": "# v3", "notes.md": "n"})

    versions = await svc.list_versions(skill.id)
    assert [(v.reason, v.s3_path) for v in versions] == [
        ("create", _own({"SKILL.md": b"# v1"})),
        ("edit", _own({"SKILL.md": b"# v2"})),
        ("edit", _own({"SKILL.md": b"# v3", "notes.md": b"n"})),
    ]
    assert [v.digest for v in versions] == [
        package_digest({"SKILL.md": b"# v1"}),
        package_digest({"SKILL.md": b"# v2"}),
        package_digest({"SKILL.md": b"# v3", "notes.md": b"n"}),
    ]
    # Nothing was rewritten: every version's files are still what they were.
    assert s3.under(versions[0].s3_path) == {"SKILL.md": b"# v1"}
    assert s3.under(versions[1].s3_path) == {"SKILL.md": b"# v2"}


async def test_an_edit_that_changes_nothing_records_no_version():
    svc, _, _, _ = _service()
    skill = await svc.create_from_content(SkillCreateFromContent(content="# same"))
    skill.workspace_id = "w1"

    await svc.set_content(skill.id, "# same")

    assert [v.reason for v in await svc.list_versions(skill.id)] == ["create"]


async def test_rolling_back_points_the_skill_at_the_earlier_package():
    svc, _, _, _ = _service()
    skill = await svc.create_from_content(SkillCreateFromContent(content="# v1"))
    skill.workspace_id = "w1"
    await svc.set_content(skill.id, "# v2")
    first = (await svc.list_versions(skill.id))[0]

    rolled = await svc.rollback(skill.id, first.id)

    assert rolled.s3_path == first.s3_path
    assert await svc.read_skill_md(rolled) == "# v1"
    assert [v.reason for v in await svc.list_versions(skill.id)] == ["create", "edit", "rollback"]


async def test_a_version_of_another_skill_is_not_found():
    svc, _, _, _ = _service()
    one = await svc.create_from_content(SkillCreateFromContent(content="---\nname: a\n---\n# a"))
    other = await svc.create_from_content(SkillCreateFromContent(content="---\nname: b\n---\n# b"))
    foreign = (await svc.list_versions(other.id))[0]

    with pytest.raises(SkillVersionNotFoundError):
        await svc.rollback(one.id, foreign.id)
    with pytest.raises(SkillVersionNotFoundError):
        await svc.rollback(one.id, uuid4())


async def test_rolling_an_edited_install_back_to_its_catalog_version_repins_it():
    item = _pointer_item()
    svc, repo, catalog, _ = _service(catalog=FakeCatalogRepo([item]))
    skill = await svc.install_catalog_skill(UUID(item.id))
    skill.workspace_id = "w1"
    edited = await svc.set_content(skill.id, "# my edit")
    assert is_customized(edited)
    installed = (await svc.list_versions(skill.id))[0]
    assert (installed.reason, installed.catalog_version) == ("install", item.version)

    rolled = await svc.rollback(skill.id, installed.id)

    assert not is_customized(rolled)
    assert rolled.s3_path == f"skills/catalog/{package_digest(PDF)}/"
    assert catalog.installed[-1] == (item.id, str(skill.id), item.version)


async def test_deleting_a_skill_keeps_its_packages():
    svc, _, _, s3 = _service()
    skill = await svc.create_from_content(SkillCreateFromContent(content="# kept"))
    skill.workspace_id = "w1"

    assert await svc.delete(skill.id)

    assert s3.under(_own({"SKILL.md": b"# kept"})) == {"SKILL.md": b"# kept"}


async def test_a_run_pinned_to_an_own_package_keeps_reading_it_after_an_edit_and_a_rollback():
    svc, _, _, _ = _service()
    skill = await svc.create_from_content(SkillCreateFromContent(content="# v1"))
    skill.workspace_id = "w1"
    pinned = skill.s3_path

    await svc.set_content(skill.id, "# v2")
    assert await svc.read_skill_md(skill, at=pinned) == "# v1"
    await svc.set_content(skill.id, "# v3")
    second = (await svc.list_versions(skill.id))[1]
    await svc.rollback(skill.id, second.id)

    assert await svc.read_skill_md(skill, at=pinned) == "# v1"
    assert await svc.read_skill_md(skill) == "# v2"
