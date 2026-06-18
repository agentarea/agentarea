"""Skill catalog read-path + copy-on-write tests (ADR-003).

Built-in skills live in the registry catalog (``registry_items`` of
``registry_type='skills'``) and are projected into the skill list read-only; a
real tenant ``skills`` row is created only on edit (copy-on-write). These tests
exercise that wiring with light fakes, no database — mirroring
``test_catalog_agents.py``.
"""

from datetime import datetime
from uuid import UUID, uuid4

from agentarea_agents.application.skill_service import (
    SkillService,
    _project_catalog_skill,
)
from agentarea_agents.domain.skill_models import Skill
from agentarea_agents.infrastructure.catalog_skill_repository import (
    CatalogSkillItem,
    CatalogSkillRepository,
)
from agentarea_common.auth.context import UserContext


def _item(item_id=None, name="Built-in", version="1", installed_version=None, spec=None):
    now = datetime.now()
    return CatalogSkillItem(
        id=item_id or str(uuid4()),
        name=name,
        description="desc",
        version=version,
        spec=spec or {"source_type": "content", "content": "# Built-in"},
        installed_entity_id=None,
        installed_version=installed_version,
        created_at=now,
        updated_at=now,
    )


class FakeSkillRepo:
    def __init__(self, skills=None):
        self._skills = skills or []
        self.created_kwargs = []

    async def list_all(self):
        return list(self._skills)

    async def get_by_id(self, _id):
        return next((s for s in self._skills if str(s.id) == str(_id)), None)

    async def get_by_slug(self, _slug):
        return None

    async def get_by_registry_item_id(self, registry_item_id):
        return next(
            (
                s
                for s in self._skills
                if str(getattr(s, "registry_item_id", "")) == str(registry_item_id)
            ),
            None,
        )

    async def create(self, **kwargs):
        self.created_kwargs.append(kwargs)
        skill = Skill(id=uuid4(), **kwargs)
        self._skills.append(skill)
        return skill

    async def update(self, skill_id, **kwargs):
        skill = await self.get_by_id(skill_id)
        if skill is None:
            return None
        for k, v in kwargs.items():
            setattr(skill, k, v)
        return skill


class FakeCatalogRepo:
    def __init__(self, items=None):
        self._items = items or []
        self.installed = []

    async def list_items(self):
        return list(self._items)

    async def get_item(self, item_id):
        return next((i for i in self._items if i.id == item_id), None)

    async def mark_installed(self, item_id, entity_id, installed_version):
        self.installed.append((item_id, entity_id, installed_version))


class CapturingSession:
    def __init__(self):
        self.executions = []

    async def execute(self, query, params=None):
        self.executions.append((str(query), params or {}))


class FakeFactory:
    def __init__(self, repo, user_context):
        self._repo = repo
        self.user_context = user_context
        self.session = object()

    def create_repository(self, _cls):
        return self._repo


def _service(repo, catalog, workspace_id="w1"):
    uc = UserContext(user_id="u1", workspace_id=workspace_id)
    svc = SkillService(FakeFactory(repo, uc), uc)
    svc._get_repository = lambda: repo
    svc._get_catalog_repository = lambda: catalog
    return svc


def test_project_catalog_skill_marks_read_only_with_provenance():
    item = _item(
        spec={
            "source_type": "content",
            "content": "# Hello",
            "source_url": "https://example.com",
            "network_scope": "private",
        }
    )
    skill = _project_catalog_skill(item)
    assert str(skill.id) == item.id
    assert skill.registry_item_id == item.id
    assert skill.is_catalog is True
    assert skill.update_available is False
    assert skill.content == "# Hello"
    assert skill.source_type == "content"
    assert skill.source_url == "https://example.com"
    assert skill.created_at == item.created_at
    assert skill.updated_at == item.updated_at


async def test_get_with_catalog_falls_back_to_projection():
    item = _item()
    svc = _service(FakeSkillRepo(), FakeCatalogRepo([item]))
    skill = await svc.get_with_catalog(UUID(item.id))
    assert skill is not None
    assert str(skill.id) == item.id
    assert getattr(skill, "is_catalog", False) is True


async def test_get_with_catalog_returns_none_for_unknown():
    svc = _service(FakeSkillRepo(), FakeCatalogRepo([]))
    assert await svc.get_with_catalog(uuid4()) is None


async def test_list_shadows_forked_and_projects_unforked():
    item_unforked = _item(name="Unforked", version="1")
    item_forked = _item(name="Forked", version="2", installed_version="1")
    forked_copy = Skill(
        id=uuid4(),
        name="Forked copy",
        slug="forked-copy",
        source_type="content",
        registry_item_id=item_forked.id,
    )
    repo = FakeSkillRepo([forked_copy])
    svc = _service(repo, FakeCatalogRepo([item_unforked, item_forked]))

    result = await svc.list()
    ids = [str(s.id) for s in result]

    # The user's forked copy is present; the catalog item it came from is shadowed.
    assert str(forked_copy.id) in ids
    assert item_forked.id not in ids
    # The un-forked catalog item is projected read-only.
    assert item_unforked.id in ids
    projection = next(s for s in result if str(s.id) == item_unforked.id)
    assert getattr(projection, "is_catalog", False) is True
    # A newer catalog version flags the forked copy for update.
    assert getattr(forked_copy, "update_available", False) is True


async def test_fork_creates_owned_copy_and_marks_installed():
    item = _item(
        name="Builtin A",
        version="3",
        spec={
            "source_type": "content",
            "content": "# C",
            "source_url": "https://x",
            "network_scope": "private",
        },
    )
    repo = FakeSkillRepo()
    catalog = FakeCatalogRepo([item])
    svc = _service(repo, catalog)

    skill = await svc._fork_catalog_skill(item)

    assert skill.registry_item_id == item.id
    kw = repo.created_kwargs[0]
    assert kw["registry_item_id"] == item.id
    assert kw["content"] == "# C"
    assert kw["source_type"] == "content"
    assert kw["source_url"] == "https://x"
    # The install is recorded on the catalog item with the new skill id + version.
    assert catalog.installed == [(item.id, str(skill.id), "3")]


async def test_catalog_skill_install_state_is_workspace_scoped():
    session = CapturingSession()
    repo = CatalogSkillRepository(session, UserContext(user_id="u1", workspace_id="w1"))

    await repo.mark_installed(str(uuid4()), str(uuid4()), "3")

    query, params = session.executions[0]
    assert "registry_item_installs" in query
    assert "UPDATE registry_items" not in query
    assert params["workspace_id"] == "w1"


async def test_install_catalog_skill_is_idempotent():
    item = _item(name="Builtin Install", version="4")
    repo = FakeSkillRepo()
    catalog = FakeCatalogRepo([item])
    svc = _service(repo, catalog)

    first = await svc.install_catalog_skill(UUID(item.id))
    second = await svc.install_catalog_skill(UUID(item.id))

    assert first is not None
    assert second is not None
    assert first.id == second.id
    assert len(repo.created_kwargs) == 1
    assert repo.created_kwargs[0]["registry_item_id"] == item.id


async def test_update_on_catalog_id_forks_tenant_copy():
    """Editing a built-in skill by its catalog id forks a real tenant row with
    the full spec, then applies the edit to that copy (copy-on-write)."""
    from agentarea_agents.schemas.skills_dto import SkillEditMetadata

    item = _item(
        name="Builtin B",
        version="5",
        spec={"source_type": "content", "content": "# Orig"},
    )
    repo = FakeSkillRepo()
    catalog = FakeCatalogRepo([item])
    svc = _service(repo, catalog)

    updated = await svc.update(UUID(item.id), SkillEditMetadata(description="new desc"))

    assert updated is not None
    # A new tenant row was created (id differs from the catalog item id).
    assert str(updated.id) != item.id
    assert updated.registry_item_id == item.id
    assert updated.content == "# Orig"
    assert updated.description == "new desc"
    assert catalog.installed
    assert catalog.installed[0][0] == item.id


async def test_set_content_on_catalog_id_forks_tenant_copy():
    item = _item(name="Builtin C", spec={"source_type": "content", "content": "# Old"})
    repo = FakeSkillRepo()
    catalog = FakeCatalogRepo([item])
    svc = _service(repo, catalog)

    updated = await svc.set_content(UUID(item.id), "# New content")

    assert updated is not None
    assert str(updated.id) != item.id
    assert updated.registry_item_id == item.id
    assert updated.content == "# New content"


async def test_list_paginated_merges_catalog_and_dedups():
    item_unforked = _item(name="Cat", version="1")
    custom = Skill(id=uuid4(), name="Custom", slug="custom", source_type="content")
    repo = FakeSkillRepo([custom])
    svc = _service(repo, FakeCatalogRepo([item_unforked]))

    page, total = await svc.list_paginated(limit=50, offset=0)
    ids = {str(s.id) for s in page}

    assert total == 2
    assert str(custom.id) in ids
    assert item_unforked.id in ids


async def test_list_paginated_from_registry_filter():
    item_unforked = _item(name="Cat", version="1")
    custom = Skill(id=uuid4(), name="Custom", slug="custom", source_type="content")
    repo = FakeSkillRepo([custom])
    svc = _service(repo, FakeCatalogRepo([item_unforked]))

    # Catalog projections carry registry_item_id, custom skills do not.
    page, _total = await svc.list_paginated(limit=50, offset=0, from_registry=True)
    ids = {str(s.id) for s in page}
    assert ids == {item_unforked.id}

    page, _total = await svc.list_paginated(limit=50, offset=0, from_registry=False)
    ids = {str(s.id) for s in page}
    assert ids == {str(custom.id)}


async def test_isolation_built_in_visible_custom_from_other_workspace_not():
    """A built-in catalog skill IS visible to every workspace; another
    workspace's custom skill is NOT (it never appears in this workspace's
    tenant rows, and only catalog items are merged in)."""
    item_builtin = _item(name="Shared built-in", version="1")
    # This workspace's repo returns only its own rows (the base repo filter would
    # exclude other workspaces' customs); the catalog is global.
    repo = FakeSkillRepo([])
    svc = _service(repo, FakeCatalogRepo([item_builtin]), workspace_id="w2")

    result = await svc.list()
    ids = [str(s.id) for s in result]

    # Built-in catalog skill is visible.
    assert item_builtin.id in ids
    # No foreign custom skill leaked in (only the catalog projection is present).
    assert len(result) == 1
