"""Agent catalog read-path + copy-on-write tests (ADR-003).

Built-in agents live in the registry catalog (``registry_items``) and are
projected into the agent list read-only; a real tenant ``agents`` row is created
only on edit (copy-on-write). These tests exercise that wiring with light fakes,
no database.
"""

from uuid import UUID, uuid4

from agentarea_agents.application.agent_service import (
    AgentService,
    _preferred_models_from_spec,
    _project_catalog_item,
)
from agentarea_agents.domain.models import Agent
from agentarea_agents.infrastructure.catalog_agent_repository import (
    CatalogAgentItem,
    CatalogAgentRepository,
    pick_model_instance_id,
)
from agentarea_common.auth.context import UserContext


def _item(item_id=None, name="Built-in", version="1", installed_version=None, spec=None):
    return CatalogAgentItem(
        id=item_id or str(uuid4()),
        name=name,
        description="desc",
        version=version,
        spec=spec or {"instruction": "do x", "model_id": "m1"},
        installed_entity_id=None,
        installed_version=installed_version,
    )


class FakeAgentRepo:
    def __init__(self, agents=None):
        self._agents = agents or []
        self.created_kwargs = []

    async def list_all(self):
        return list(self._agents)

    async def get(self, _id):
        return next((a for a in self._agents if str(a.id) == str(_id)), None)

    async def get_by_slug(self, _slug):
        return None

    async def get_by_registry_item_id(self, registry_item_id):
        return next(
            (a for a in self._agents if getattr(a, "registry_item_id", None) == registry_item_id),
            None,
        )

    async def create(self, **kwargs):
        agent = Agent(id=uuid4(), **kwargs)
        self.created_kwargs.append(kwargs)
        self._agents.append(agent)
        return agent


class FakeCatalogRepo:
    def __init__(self, items=None, instance_ids_by_name=None):
        self._items = items or []
        self.installed = []
        self._instance_ids_by_name = instance_ids_by_name or {}

    async def list_items(self):
        return list(self._items)

    async def get_item(self, item_id):
        return next((i for i in self._items if i.id == item_id), None)

    async def mark_installed(self, item_id, entity_id, installed_version):
        self.installed.append((item_id, entity_id, installed_version))

    async def model_instance_ids_by_name(self):
        return dict(self._instance_ids_by_name)

    async def resolve_model_instance_id(self, preferred_models):
        for name in preferred_models:
            if name in self._instance_ids_by_name:
                return self._instance_ids_by_name[name]
        return None


class FakeFactory:
    def __init__(self, repo, user_context):
        self._repo = repo
        self.user_context = user_context
        self.session = object()

    def create_repository(self, _cls):
        return self._repo


class FakeBroker:
    async def publish(self, _event):
        pass


class FakeAuthz:
    async def can_write_workspace(self, _user_context, _workspace_id):
        return True

    async def get_accessible_workspaces(self, user_context):
        return [user_context.workspace_id]


class CapturingSession:
    def __init__(self):
        self.executions = []

    async def execute(self, query, params=None):
        self.executions.append((str(query), params or {}))


def _service(repo, catalog):
    uc = UserContext(user_id="u1", workspace_id="w1")
    svc = AgentService(FakeFactory(repo, uc), FakeBroker(), FakeAuthz())
    svc._get_agent_repository = lambda: repo
    svc._get_catalog_repository = lambda: catalog
    return svc


def test_project_catalog_item_marks_read_only_with_provenance():
    item = _item(
        spec={"instruction": "hello", "preferred_models": ["gpt-4o"], "tools": [{"a": 1}], "planning": True}
    )
    # The resolved per-workspace model instance is passed in by the service.
    agent = _project_catalog_item(item, model_id="instance-123")
    assert str(agent.id) == item.id
    assert agent.registry_item_id == item.id
    assert agent.is_catalog is True
    assert agent.update_available is False
    assert agent.instruction == "hello"
    assert agent.model_id == "instance-123"
    assert agent.tools == [{"a": 1}]


def test_project_catalog_item_without_resolved_model_has_no_model():
    # The catalog never carries a runnable model_id; with nothing resolved the
    # projection has no model bound (not a bogus slug).
    item = _item(spec={"instruction": "hello", "preferred_models": ["gpt-4o"]})
    agent = _project_catalog_item(item)
    assert agent.model_id is None


async def test_get_with_catalog_falls_back_to_projection():
    item = _item()
    svc = _service(FakeAgentRepo(), FakeCatalogRepo([item]))
    agent = await svc.get_with_catalog(UUID(item.id))
    assert agent is not None
    assert str(agent.id) == item.id
    assert getattr(agent, "is_catalog", False) is True


async def test_get_with_catalog_returns_none_for_unknown():
    svc = _service(FakeAgentRepo(), FakeCatalogRepo([]))
    assert await svc.get_with_catalog(uuid4()) is None


async def test_get_catalog_by_slug_resolves_projected_slug():
    # A built-in catalog agent is reachable by the slug it is projected with
    # (generate_slug(name)), even though it has no tenant ``agents`` row.
    item = _item(name="Customer Support")
    svc = _service(FakeAgentRepo(), FakeCatalogRepo([item]))
    agent = await svc.get_catalog_by_slug("customer-support")
    assert agent is not None
    assert str(agent.id) == item.id
    assert getattr(agent, "is_catalog", False) is True


async def test_get_catalog_by_slug_returns_none_for_unknown():
    svc = _service(FakeAgentRepo(), FakeCatalogRepo([_item(name="Other")]))
    assert await svc.get_catalog_by_slug("customer-support") is None


async def test_list_shadows_forked_and_projects_unforked():
    item_unforked = _item(name="Unforked", version="1")
    item_forked = _item(name="Forked", version="2", installed_version="1")
    forked_copy = Agent(
        id=uuid4(), name="Forked copy", slug="forked-copy", registry_item_id=item_forked.id
    )
    repo = FakeAgentRepo([forked_copy])
    svc = _service(repo, FakeCatalogRepo([item_unforked, item_forked]))

    result = await svc.list(include_catalog=True)
    ids = [str(a.id) for a in result]

    # The user's forked copy is present; the catalog item it came from is shadowed.
    assert str(forked_copy.id) in ids
    assert item_forked.id not in ids
    # The un-forked catalog item is projected read-only.
    assert item_unforked.id in ids
    projection = next(a for a in result if str(a.id) == item_unforked.id)
    assert getattr(projection, "is_catalog", False) is True
    # A newer catalog version flags the forked copy for update.
    assert getattr(forked_copy, "update_available", False) is True


async def test_list_excludes_catalog_by_default():
    # The working-set list (default) returns only tenant agents — catalog lives
    # in Explore. Forked copies still get their update_available flag.
    item_unforked = _item(name="Unforked", version="1")
    item_forked = _item(name="Forked", version="2", installed_version="1")
    forked_copy = Agent(
        id=uuid4(), name="Forked copy", slug="forked-copy", registry_item_id=item_forked.id
    )
    repo = FakeAgentRepo([forked_copy])
    svc = _service(repo, FakeCatalogRepo([item_unforked, item_forked]))

    result = await svc.list()
    ids = [str(a.id) for a in result]

    assert ids == [str(forked_copy.id)]
    assert item_unforked.id not in ids
    assert all(not getattr(a, "is_catalog", False) for a in result)
    # Update flagging still works without projecting the catalog.
    assert getattr(forked_copy, "update_available", False) is True


async def test_install_catalog_agent_forks_once():
    item = _item(name="Customer Support", version="3")
    repo = FakeAgentRepo()
    catalog = FakeCatalogRepo([item])
    svc = _service(repo, catalog)

    agent = await svc.install_catalog_agent(UUID(item.id))

    assert agent is not None
    assert agent.registry_item_id == item.id
    assert len(repo.created_kwargs) == 1
    assert catalog.installed == [(item.id, str(agent.id), "3")]


async def test_install_catalog_agent_is_idempotent():
    item = _item(name="Customer Support")
    repo = FakeAgentRepo()
    svc = _service(repo, FakeCatalogRepo([item]))

    first = await svc.install_catalog_agent(UUID(item.id))
    second = await svc.install_catalog_agent(UUID(item.id))

    # Second install returns the existing copy; no duplicate fork.
    assert first.id == second.id
    assert len(repo.created_kwargs) == 1


async def test_install_catalog_agent_unknown_returns_none():
    svc = _service(FakeAgentRepo(), FakeCatalogRepo([]))
    assert await svc.install_catalog_agent(uuid4()) is None


async def test_fork_resolves_preferred_model_to_workspace_instance():
    item = _item(
        name="Builtin A",
        version="3",
        spec={
            "instruction": "ins",
            "preferred_models": ["gpt-4o"],
            "tools": [{"x": 1}],
            "planning": True,
        },
    )
    repo = FakeAgentRepo()
    catalog = FakeCatalogRepo([item], instance_ids_by_name={"gpt-4o": "inst-gpt4o"})
    svc = _service(repo, catalog)

    agent = await svc._fork_catalog_agent(item)

    assert agent.registry_item_id == item.id
    kw = repo.created_kwargs[0]
    assert kw["registry_item_id"] == item.id
    assert kw["instruction"] == "ins"
    # The catalog's preferred slug is resolved to the workspace model-instance id.
    assert kw["model_id"] == "inst-gpt4o"
    assert kw["tools"] == [{"x": 1}]
    # The install is recorded on the catalog item with the new agent id + version.
    assert catalog.installed == [(item.id, str(agent.id), "3")]


async def test_fork_without_matching_model_installs_without_model():
    # No configured instance matches the preferred model: the agent forks with no
    # model bound rather than copying a non-existent model reference.
    item = _item(
        name="Builtin A",
        spec={"instruction": "ins", "preferred_models": ["gpt-4o"]},
    )
    repo = FakeAgentRepo()
    catalog = FakeCatalogRepo([item], instance_ids_by_name={})
    svc = _service(repo, catalog)

    await svc._fork_catalog_agent(item)

    assert repo.created_kwargs[0]["model_id"] is None


async def test_fork_legacy_model_id_slug_is_treated_as_preferred():
    # Older catalog specs stored a single model slug under ``model_id`` (never an
    # instance UUID); it is honoured as a one-element preference.
    item = _item(
        name="Legacy",
        spec={"instruction": "ins", "model_id": "gpt-4o"},
    )
    repo = FakeAgentRepo()
    catalog = FakeCatalogRepo([item], instance_ids_by_name={"gpt-4o": "inst-gpt4o"})
    svc = _service(repo, catalog)

    await svc._fork_catalog_agent(item)

    assert repo.created_kwargs[0]["model_id"] == "inst-gpt4o"


def test_preferred_models_from_spec_reads_list():
    assert _preferred_models_from_spec({"preferred_models": ["a", "b"]}) == ["a", "b"]


def test_preferred_models_from_spec_drops_non_strings():
    assert _preferred_models_from_spec({"preferred_models": ["a", None, 1, "b", ""]}) == ["a", "b"]


def test_preferred_models_from_spec_legacy_model_id_fallback():
    # Legacy catalog specs stored a single slug under model_id (never a UUID).
    assert _preferred_models_from_spec({"model_id": "gpt-4o"}) == ["gpt-4o"]


def test_preferred_models_from_spec_empty():
    assert _preferred_models_from_spec({}) == []


def test_pick_model_instance_id_honours_priority_order():
    by_name = {"b": "inst-b", "c": "inst-c"}
    # "a" has no instance; "b" is the first preferred one that does.
    assert pick_model_instance_id(["a", "b", "c"], by_name) == "inst-b"


def test_pick_model_instance_id_returns_none_when_no_match():
    assert pick_model_instance_id(["a", "b"], {"c": "inst-c"}) is None
    assert pick_model_instance_id([], {"a": "inst-a"}) is None


async def test_model_instance_ids_by_name_is_workspace_scoped_first_wins():
    class Row:
        def __init__(self, model_name, _id):
            self.model_name = model_name
            self.id = _id

    class Result:
        def __init__(self, rows):
            self._rows = rows

        def fetchall(self):
            return self._rows

    class FakeSession:
        def __init__(self, rows):
            self._rows = rows
            self.params = None

        async def execute(self, query, params=None):
            self.params = params or {}
            return Result(self._rows)

    session = FakeSession([Row("gpt-4o", "inst-1"), Row("gpt-4o", "inst-2"), Row("o3", "inst-3")])
    repo = CatalogAgentRepository(session, UserContext(user_id="u1", workspace_id="w1"))

    by_name = await repo.model_instance_ids_by_name()

    assert by_name == {"gpt-4o": "inst-1", "o3": "inst-3"}  # first active instance per name wins
    assert session.params["workspace_id"] == "w1"


async def test_catalog_agent_install_state_is_workspace_scoped():
    session = CapturingSession()
    repo = CatalogAgentRepository(session, UserContext(user_id="u1", workspace_id="w1"))

    await repo.mark_installed(str(uuid4()), str(uuid4()), "3")

    query, params = session.executions[0]
    assert "registry_item_installs" in query
    assert "UPDATE registry_items" not in query
    assert params["workspace_id"] == "w1"
