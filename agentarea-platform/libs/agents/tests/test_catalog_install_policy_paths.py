"""Every way a catalog item becomes a workspace's own asks the install policy (ADR-0044).

Installing a catalog skill or agent, attaching a catalog skill to an agent on
create or update (presets), editing a catalog skill or agent (which forks it),
and moving an installed skill to its item's next version: a DENY rule on the
item's registry trust refuses each before anything is written. The services
build the real policy check over the session they were given; the rules live
in an in-memory table.
"""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest
from agentarea_agents.application.agent_service import AgentService
from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.schemas.dto import AgentCreate, AgentUpdate
from agentarea_agents.schemas.skills_dto import SkillEditMetadata
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_governance.application.catalog_install import CatalogInstallRefusedError
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from .fake_s3 import fake_storage
from .test_catalog_agents import FakeAgentRepo, FakeAuthz, FakeBroker
from .test_catalog_agents import FakeCatalogRepo as FakeAgentCatalog
from .test_catalog_agents import _item as _agent_item
from .test_catalog_skills import FakeCatalogRepo, FakeFactory, FakeSkillRepo
from .test_catalog_skills import _item as _skill_item

CALLER = UserContext(user_id="u1", workspace_id="w1")
REGISTRY = str(uuid4())


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: BaseModel.metadata.create_all(c, tables=[PolicyRuleORM.__table__])
        )
    async with async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)() as s:
        yield s
    await engine.dispose()


async def _deny_community(session) -> PolicyRule:
    rule = await PolicyRuleRepository(session, CALLER).create(
        PolicyRule(
            subject_type=PolicySubjectType.WORKSPACE,
            subject_id=CALLER.workspace_id,
            target="registry_trust:community",
            effect=PolicyEffect.DENY,
        )
    )
    await session.commit()
    return rule


def _from(item, trust: str):
    return replace(item, registry_id=REGISTRY, registry_trust=trust)


class InstallsOnly(FakeSkillRepo):
    async def set_skills(self, *_args):
        pass


def _skills(session, items, skills_repo=None):
    repo = skills_repo or FakeSkillRepo()
    catalog = FakeCatalogRepo(items)
    factory = FakeFactory(repo, CALLER)
    factory.session = session
    svc = SkillService(factory, CALLER, storage_service=fake_storage()[0])
    svc._get_repository = lambda: repo
    svc._get_catalog_repository = lambda: catalog
    return svc, repo, catalog


@pytest.fixture
def community_skill():
    return _from(
        _skill_item(spec={"source_type": "content", "content": "# Community"}), "community"
    )


@pytest.mark.parametrize(
    "edit",
    [
        pytest.param(lambda svc, i: svc.install_catalog_skill(UUID(i)), id="install"),
        pytest.param(
            lambda svc, i: svc.update(UUID(i), SkillEditMetadata(name="mine")), id="edit-metadata"
        ),
        pytest.param(lambda svc, i: svc.set_content(UUID(i), "# Mine"), id="edit-content"),
        pytest.param(
            lambda svc, i: svc.replace_package_from_files(UUID(i), {"SKILL.md": "# Mine"}),
            id="edit-files",
        ),
    ],
)
async def test_a_denied_catalog_skill_is_neither_installed_nor_forked(
    session, community_skill, edit
):
    await _deny_community(session)
    svc, repo, catalog = _skills(session, [community_skill])

    with pytest.raises(CatalogInstallRefusedError, match="registry_trust:community"):
        await edit(svc, community_skill.id)

    assert repo.created_kwargs == []
    assert catalog.installed == []


async def test_an_allowed_catalog_skill_installs(session, community_skill):
    await _deny_community(session)
    official = _from(_skill_item(), "official")
    svc, repo, catalog = _skills(session, [community_skill, official])

    skill = await svc.install_catalog_skill(UUID(official.id))

    assert catalog.installed == [(official.id, str(skill.id), official.version)]


async def test_a_denied_registry_stops_an_installed_skills_update(session, community_skill):
    svc, repo, catalog = _skills(session, [community_skill])
    skill = await svc.install_catalog_skill(UUID(community_skill.id))
    catalog._items = [replace(community_skill, version="2", installed_version="1")]
    await _deny_community(session)

    with pytest.raises(CatalogInstallRefusedError):
        await svc.update_from_catalog(skill.id)

    assert catalog.installed == [(community_skill.id, str(skill.id), "1")]


def _agents(session, agent_items, skill_items):
    agents = FakeAgentRepo()
    skills = InstallsOnly()
    agent_catalog = FakeAgentCatalog(agent_items)
    skill_catalog = FakeCatalogRepo(skill_items)

    class Factory(FakeFactory):
        def create_repository(self, cls):
            return skills if cls.__name__ == "SkillRepository" else agents

    factory = Factory(agents, CALLER)
    factory.session = session
    svc = AgentService(factory, FakeBroker(), FakeAuthz())
    svc._get_agent_repository = lambda: agents
    svc._get_catalog_repository = lambda: agent_catalog
    return svc, agents, skills, agent_catalog, skill_catalog


@pytest.fixture
def patched_skill_catalog(monkeypatch):
    def install(skill_catalog):
        monkeypatch.setattr(SkillService, "_get_catalog_repository", lambda _self: skill_catalog)
        monkeypatch.setattr(
            SkillService, "storage_service", property(lambda _self: fake_storage()[0])
        )

    return install


async def test_a_denied_catalog_agent_is_neither_installed_nor_forked_on_edit(session):
    await _deny_community(session)
    item = _from(_agent_item(spec={"instruction": "x", "tools": []}), "community")
    svc, agents, _, catalog, _ = _agents(session, [item], [])

    with pytest.raises(CatalogInstallRefusedError):
        await svc.install_catalog_agent(UUID(item.id))
    with pytest.raises(CatalogInstallRefusedError):
        await svc.update_agent(UUID(item.id), AgentUpdate(name="mine"))

    assert agents.created_kwargs == []
    assert catalog.installed == []


@pytest.mark.parametrize("path", ["create", "update"])
async def test_a_denied_catalog_skill_is_not_attached_to_an_agent(
    session, community_skill, patched_skill_catalog, path
):
    await _deny_community(session)
    svc, agents, skills, _, skill_catalog = _agents(session, [], [community_skill])
    patched_skill_catalog(skill_catalog)
    skill_ids = [UUID(community_skill.id)]

    with pytest.raises(CatalogInstallRefusedError):
        if path == "create":
            await svc.create_agent(
                AgentCreate(
                    name="a", description="", instruction="x", tools=[], skill_ids=skill_ids
                )
            )
        else:
            await svc.update_agent(uuid4(), AgentUpdate(skill_ids=skill_ids))

    assert skills.created_kwargs == []
    assert agents.created_kwargs == []
    assert skill_catalog.installed == []


async def test_a_denied_catalog_skill_does_not_run_from_the_catalog(session, community_skill):
    # A run names catalog skills by id and reads them without installing.
    await _deny_community(session)
    official = _from(_skill_item(), "official")
    svc, _, _ = _skills(session, [community_skill, official])

    with pytest.raises(CatalogInstallRefusedError, match="registry_trust:community"):
        await svc.get_with_catalog(community_skill.id, to_run=True)

    assert (await svc.get_with_catalog(official.id, to_run=True)).name == official.name
    # Browsing still shows what the policy keeps out of runs.
    assert (await svc.get_with_catalog(community_skill.id)).is_catalog


async def test_a_denied_catalog_agent_does_not_run_from_its_definition(session):
    await _deny_community(session)
    item = _from(_agent_item(spec={"instruction": "x", "tools": []}), "community")
    svc, *_ = _agents(session, [item], [])

    with pytest.raises(CatalogInstallRefusedError):
        await svc.get_with_catalog(UUID(item.id), to_run=True)

    assert (await svc.get_with_catalog(UUID(item.id))).is_catalog


@pytest.mark.parametrize(
    "read",
    [
        pytest.param(lambda svc, i: svc.get_skill_files(i, to_run=True), id="list"),
        pytest.param(lambda svc, i: svc.get_skill_file_url(i, "SKILL.md", to_run=True), id="url"),
        pytest.param(
            lambda svc, i: svc.get_skill_file_content(i, "SKILL.md", to_run=True), id="content"
        ),
    ],
)
async def test_a_run_cannot_read_a_denied_catalog_skills_files(session, community_skill, read):
    await _deny_community(session)
    svc, _, _ = _skills(session, [community_skill])

    with pytest.raises(CatalogInstallRefusedError):
        await read(svc, community_skill.id)
    # The API's preview stays open.
    assert await svc.get_skill_file_content(community_skill.id, "SKILL.md") == b"# Community"


async def test_the_skills_toolset_reads_package_files_as_a_run(monkeypatch):
    from contextlib import asynccontextmanager

    from agentarea_agents.application import skill_service
    from agentarea_agents.tools import skills_toolset
    from agentarea_agents_sdk.tools.base_tool import ToolError

    asked: list[tuple[str, bool]] = []

    class Refusing:
        def __init__(self, **_kwargs):
            pass

        async def get_skill_files(self, _id, include_urls=False, *, to_run=False):
            asked.append(("files", to_run))
            raise CatalogInstallRefusedError("Install refused by policy: registry_trust:community")

        async def get_skill_file_url(self, _id, _path, expires_in=3600, *, to_run=False):
            asked.append(("url", to_run))
            raise CatalogInstallRefusedError("Install refused by policy: registry_trust:community")

        async def get_skill_file_content(self, _id, _path, *, to_run=False):
            asked.append(("content", to_run))
            raise CatalogInstallRefusedError("Install refused by policy: registry_trust:community")

    @asynccontextmanager
    async def context():
        yield None, CALLER, None, None, None

    monkeypatch.setattr(skill_service, "SkillService", Refusing)
    monkeypatch.setattr(skills_toolset, "platform_read_context", context)
    toolset = skills_toolset.SkillsToolset()
    item = str(uuid4())

    for call in (
        toolset.list_files(item),
        toolset.get_file(item, "SKILL.md", as_url=True),
        toolset.get_file(item, "SKILL.md"),
    ):
        with pytest.raises(ToolError, match="refused by policy"):
            await call

    assert asked == [("files", True), ("url", True), ("content", True)]


async def test_an_installed_skill_is_refused_at_run_time_once_its_registry_trust_is_denied(
    session, community_skill
):
    # An install was decided once; a rule written later holds for it at run time.
    svc, _, _ = _skills(session, [community_skill])
    skill = await svc.install_catalog_skill(UUID(community_skill.id))
    assert await svc.get_with_catalog(skill.id, to_run=True) is not None

    rule = await _deny_community(session)
    with pytest.raises(CatalogInstallRefusedError, match="registry_trust:community"):
        await svc.get_with_catalog(skill.id, to_run=True)
    with pytest.raises(CatalogInstallRefusedError):
        await svc.require_runnable(skill)
    # Outside a run the workspace still sees and manages its install.
    assert await svc.get_with_catalog(skill.id) is not None

    await PolicyRuleRepository(session, CALLER).set_enabled(rule.id, False)
    await session.commit()
    assert await svc.get_with_catalog(skill.id, to_run=True) is not None


async def test_a_skill_imported_from_github_is_refused_at_run_time_once_community_is_denied(
    session,
):
    svc, repo, _ = _skills(session, [])
    imported = await repo.create(
        slug="pdf", name="pdf", source_type="github", source_url="https://github.com/o/r/pdf"
    )
    await svc.require_runnable(imported)

    await _deny_community(session)
    with pytest.raises(CatalogInstallRefusedError, match="registry_trust:community"):
        await svc.require_runnable(imported)


async def test_a_skill_the_workspace_wrote_is_not_asked_about(session):
    await _deny_community(session)
    svc, repo, _ = _skills(session, [])
    own = await repo.create(slug="mine", name="mine", source_type="content")

    await svc.require_runnable(own)
    assert await svc.get_with_catalog(own.id, to_run=True) is own


async def test_an_installed_skill_whose_registry_item_is_gone_is_refused(session, community_skill):
    svc, _, catalog = _skills(session, [community_skill])
    skill = await svc.install_catalog_skill(UUID(community_skill.id))
    catalog._items = []

    with pytest.raises(CatalogInstallRefusedError, match="no longer exists"):
        await svc.get_with_catalog(skill.id, to_run=True)
