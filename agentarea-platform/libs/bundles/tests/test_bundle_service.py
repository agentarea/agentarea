"""BundleService: the workspace lookups and the install entry point (fake repositories)."""

from copy import deepcopy
from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_agents.application.agent_service import InvalidModelIdError
from agentarea_bundles.application.analyzer import parse_bundle
from agentarea_bundles.application.installer import BundleInstallError, BundleValidationError
from agentarea_bundles.application.service import BundleService
from agentarea_bundles.schemas.preview import EntityKind, EntityStatus
from agentarea_bundles.schemas.result import InstallAction, InstalledEntity, InstallResult
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.permission import PermissionService
from agentarea_common.di.container import register_singleton
from agentarea_triggers.logging_utils import TriggerValidationError


class AllowAll(PermissionService):
    async def check(self, user_id, permission, resource_type, resource_id):
        return True


@pytest.fixture(autouse=True)
def _permissions():
    register_singleton(PermissionService, AllowAll())


class FakeTriggerRepo:
    def __init__(self, triggers=()):
        self.triggers = list(triggers)

    async def list_all(self):
        return self.triggers


class FakeBundleRepo:
    def __init__(self, record=None):
        self.record = record
        self.writes = []

    async def get_by_name(self, name):
        return self.record

    async def update(self, id, **fields):
        self.writes.append(fields)
        return self.record

    async def create(self, **fields):
        self.writes.append(fields)
        return SimpleNamespace(id=uuid4(), **fields)


class FakeSession:
    def __init__(self):
        self.rollbacks = 0

    async def rollback(self):
        self.rollbacks += 1


class FakeFactory:
    def __init__(self, user_context, **repos):
        self.user_context = user_context
        self.repos = repos
        self.session = FakeSession()

    def create_repository(self, cls):
        return self.repos.get(cls.__name__, SimpleNamespace())


class Known:
    def __init__(self, known=None, refuse=None):
        self.known = {str(k): v for k, v in (known or {}).items()}
        self.refuse = refuse
        self.calls = []
        self.updates = []
        self.deleted = []

    def _get(self, entity_id):
        return self.known.get(str(entity_id))


class FakeAgentSvc(Known):
    fail_update = None

    async def get(self, id):
        return self._get(id)

    async def validate_config(self, model_id, tools):
        if self.refuse:
            raise self.refuse

    async def create_agent(self, payload):
        self.calls.append(payload)
        return SimpleNamespace(id=uuid4())

    async def update_agent(self, id, payload):
        if self.fail_update:
            raise self.fail_update
        self.updates.append((id, payload))
        return self._get(id)

    async def delete_agent(self, id):
        self.deleted.append(id)
        return True


class FakeGetSvc(Known):
    async def get(self, id):
        return self._get(id)


class FakeStreamSvc:
    repository_factory = SimpleNamespace(session=None)

    async def list_sources(self, stream_id):
        return []


class FakeTriggerSvc(Known):
    fail_update = None

    def __init__(self, known=None, refuse=None, fail_create=None):
        super().__init__(known, refuse)
        self.fail_create = fail_create
        self.stream_service = FakeStreamSvc()

    async def get_trigger(self, trigger_id):
        return self._get(trigger_id)

    async def validate_configuration(self, domain):
        if self.refuse:
            raise self.refuse

    async def create_trigger(self, domain):
        if self.fail_create:
            raise self.fail_create
        self.calls.append(domain)
        return SimpleNamespace(id=uuid4())

    async def update_trigger_from_payload(self, trigger_id, payload):
        if self.fail_update:
            raise self.fail_update
        self.updates.append((trigger_id, payload))
        return self._get(trigger_id)

    async def delete_trigger(self, trigger_id):
        self.deleted.append(trigger_id)
        return True


class FakeMcpServerSvc:
    def __init__(self, catalog=None):
        self.catalog = catalog or {}
        self.lookups = []

    async def get_catalog_server(self, external_id):
        self.lookups.append(external_id)
        return self.catalog.get(external_id)


def _service(
    *,
    record=None,
    agent_service=None,
    trigger_service=None,
    triggers=(),
    mcp_server_service=None,
    skill_service=None,
):
    context = UserContext(user_id="u", workspace_id="w", admin_workspaces=["w"])
    bundles = FakeBundleRepo(record)
    service = BundleService(
        repository_factory=FakeFactory(
            context,
            TriggerRepository=FakeTriggerRepo(triggers),
            InstalledBundleRepository=bundles,
        ),
        agent_service=agent_service or FakeAgentSvc(),
        mcp_server_service=mcp_server_service or FakeMcpServerSvc(),
        mcp_instance_service=FakeGetSvc(),
        skill_service=skill_service or FakeGetSvc(),
        trigger_service=trigger_service or FakeTriggerSvc(),
    )
    return service, bundles


async def test_a_trigger_is_found_by_its_name_its_agent_and_the_recorded_id():
    agent = str(uuid4())
    service, _ = _service(
        triggers=[
            SimpleNamespace(id="t-other", name="other:daily", agent_id=agent),
            SimpleNamespace(id="t-squat", name="seo:daily", agent_id=str(uuid4())),
            SimpleNamespace(id="t-seo", name="seo:daily", agent_id=agent),
        ]
    )

    assert await service.find_trigger("seo:daily", agent, None) == "t-seo"
    assert await service.find_trigger("seo:daily", agent, "t-seo") == "t-seo"
    assert await service.find_trigger("seo:daily", agent, "t-gone") is None
    assert await service.find_trigger("seo:weekly", agent, None) is None
    assert await service.find_trigger("daily", agent, None) is None


SEO = """
schema_version: "0.1.0"
name: seo
agents: [{key: lead, name: Lead, model: m, instruction: x}]
skills: [{key: sk, name: Audit, source_type: content, content: "# a"}]
automations:
  - {key: daily, type: cron, cron: "0 9 * * *", agent: lead, prompt: go}
"""


def _seo_record(*entities):
    result = InstallResult(bundle_name="seo", entities=list(entities))
    return SimpleNamespace(
        id=uuid4(),
        canonical=parse_bundle(SEO).model_dump(mode="json"),
        install_result=result.model_dump(mode="json"),
    )


def _entity(kind, key, action, entity_id):
    return InstalledEntity(kind=kind, key=key, name=key, action=action, id=str(entity_id))


async def test_the_preview_counts_only_what_the_last_install_recorded():
    agent = SimpleNamespace(id=uuid4(), status="active")
    namesake_skill = SimpleNamespace(id=uuid4(), name="Audit")
    trigger = SimpleNamespace(id=uuid4(), name="seo:daily", agent_id=agent.id)
    service, _ = _service(
        record=_seo_record(_entity(EntityKind.AGENT, "lead", InstallAction.REUSED, agent.id)),
        agent_service=FakeAgentSvc({agent.id: agent}),
        skill_service=FakeGetSvc({namesake_skill.id: namesake_skill}),
        triggers=[trigger],
    )

    preview = await service.analyze_bundle(parse_bundle(SEO))

    statuses = {(e.kind, e.key): e.status for e in preview.entities}
    assert statuses[("agent", "lead")] == EntityStatus.ALREADY_EXISTS
    assert statuses[("skill", "sk")] == EntityStatus.WILL_CREATE
    assert statuses[("automation", "daily")] == EntityStatus.ALREADY_EXISTS


async def test_an_agent_the_last_install_created_is_planned_unchanged():
    agent = SimpleNamespace(id=uuid4(), status="active")
    service, _ = _service(
        record=_seo_record(_entity(EntityKind.AGENT, "lead", InstallAction.CREATED, agent.id)),
        agent_service=FakeAgentSvc({agent.id: agent}),
    )

    preview = await service.analyze_bundle(parse_bundle(SEO))

    assert {(e.kind, e.key): e.status for e in preview.entities}[
        ("agent", "lead")
    ] == EntityStatus.UNCHANGED


async def test_a_recorded_agent_since_archived_is_planned_to_be_created():
    agent = SimpleNamespace(id=uuid4(), status="archived")
    service, _ = _service(
        record=_seo_record(_entity(EntityKind.AGENT, "lead", InstallAction.CREATED, agent.id)),
        agent_service=FakeAgentSvc({agent.id: agent}),
    )

    preview = await service.analyze_bundle(parse_bundle(SEO))

    statuses = {(e.kind, e.key): e.status for e in preview.entities}
    assert statuses[("agent", "lead")] == EntityStatus.WILL_CREATE
    assert EntityStatus.ORPHANED not in statuses.values()


async def test_a_trigger_under_the_bundle_name_for_another_agent_is_not_the_bundles():
    agent = SimpleNamespace(id=uuid4(), status="active")
    squatter = SimpleNamespace(id=uuid4(), name="seo:daily", agent_id=uuid4())
    service, _ = _service(
        record=_seo_record(_entity(EntityKind.AGENT, "lead", InstallAction.REUSED, agent.id)),
        agent_service=FakeAgentSvc({agent.id: agent}),
        triggers=[squatter],
    )

    preview = await service.analyze_bundle(parse_bundle(SEO))

    statuses = {(e.kind, e.key): e.status for e in preview.entities}
    assert statuses[("automation", "daily")] == EntityStatus.WILL_CREATE


async def test_nothing_recorded_means_everything_is_created():
    service, _ = _service(triggers=[SimpleNamespace(id=uuid4(), name="seo:daily", agent_id=uuid4())])

    preview = await service.analyze_bundle(parse_bundle(SEO))

    assert {e.status for e in preview.entities} == {EntityStatus.WILL_CREATE}


CHANNEL = """
schema_version: "0.1.0"
name: tg
setup:
  - {key: bot, label: Bot, type: secret, required: true}
agents: [{key: lead, name: Lead, model: m, instruction: x}]
channels:
  - {key: inbox, name: Inbox, agent: lead, bindings: {bot_token: "${setup.bot}"}}
"""


def _installed(*keys):
    """A record of CHANNEL installed before, owning ``keys``, with services that resolve them."""
    ids = {"lead": uuid4(), "inbox": uuid4()}
    kinds = {"lead": EntityKind.AGENT, "inbox": EntityKind.CHANNEL}
    result = InstallResult(
        bundle_name="tg",
        entities=[
            InstalledEntity(
                kind=kinds[k], key=k, name=k, action=InstallAction.CREATED, id=str(ids[k])
            )
            for k in keys
        ],
    )
    record = SimpleNamespace(
        id=uuid4(),
        canonical=parse_bundle(CHANNEL).model_dump(mode="json"),
        install_result=result.model_dump(mode="json"),
    )
    agents = FakeAgentSvc({ids["lead"]: SimpleNamespace(id=ids["lead"], status="active")})
    triggers = FakeTriggerSvc(
        {ids["inbox"]: SimpleNamespace(id=ids["inbox"], is_active=False, stream_id=uuid4())}
    )
    return record, agents, triggers


async def test_a_redeploy_that_writes_no_secret_does_not_demand_it():
    record, agents, triggers = _installed("lead", "inbox")
    service, _ = _service(record=record, agent_service=agents, trigger_service=triggers)

    await service.install(parse_bundle(CHANNEL.replace("instruction: x", "instruction: y")), {})

    assert len(agents.updates) == 1


async def test_a_redeploy_that_creates_a_channel_demands_its_secret():
    record, agents, triggers = _installed("lead")
    service, bundles = _service(record=record, agent_service=agents, trigger_service=triggers)

    with pytest.raises(BundleValidationError) as refused:
        await service.install(parse_bundle(CHANNEL), {})

    assert str(refused.value) == "package is not installable: required setup field 'bot' is missing"
    assert [i.entity_key for i in refused.value.issues] == ["bot"]
    assert triggers.calls == []
    assert bundles.writes == []


MODEL = str(uuid4())
CRON = f"""
schema_version: "0.1.0"
name: tg
agents: [{{key: lead, name: Lead, model: "{MODEL}", instruction: x}}]
automations:
  - {{key: daily, cron: "0 9 * * *", agent: lead, prompt: go}}
"""


async def test_a_model_the_workspace_refuses_blocks_before_any_write():
    agents = FakeAgentSvc(refuse=InvalidModelIdError(f"Model instance '{MODEL}' does not exist"))
    triggers = FakeTriggerSvc()
    service, bundles = _service(agent_service=agents, trigger_service=triggers)

    with pytest.raises(BundleValidationError) as refused:
        await service.install(parse_bundle(CRON), {})

    assert str(refused.value).startswith("package is not installable: agent 'lead'")
    assert any("does not exist" in i.message for i in refused.value.issues)
    assert agents.calls == []
    assert triggers.calls == []
    assert bundles.writes == []


async def test_an_unknown_toolset_blocks_before_any_write():
    agents = FakeAgentSvc()
    service, _ = _service(agent_service=agents)
    pkg = parse_bundle(CRON.replace("instruction: x", "instruction: x, toolsets: [nope/none]"))

    preview = await service.analyze_bundle(pkg)

    assert any("nope/none" in i.message for i in preview.block_issues)


async def test_a_cron_the_trigger_service_refuses_blocks_before_any_write():
    triggers = FakeTriggerSvc(
        refuse=TriggerValidationError("Cron expression must have 5 or 6 parts")
    )
    agents = FakeAgentSvc()
    service, _ = _service(agent_service=agents, trigger_service=triggers)

    with pytest.raises(BundleValidationError) as refused:
        await service.install(parse_bundle(CRON.replace("0 9 * * *", "0 9 * *")), {})

    assert any(i.entity_key == "daily" and "5 or 6" in i.message for i in refused.value.issues)
    assert agents.calls == []


class DenyEdits(PermissionService):
    def __init__(self, denied):
        self.denied = set(denied)
        self.asked = []

    async def check(self, user_id, permission, resource_type, resource_id):
        self.asked.append((permission, resource_type, resource_id))
        return resource_id not in self.denied


async def test_an_update_the_caller_may_not_edit_fails_the_whole_deploy():
    record, agents, triggers = _installed("lead", "inbox")
    lead_id = next(e["id"] for e in record.install_result["entities"] if e["key"] == "lead")
    permissions = DenyEdits({lead_id})
    register_singleton(PermissionService, permissions)
    service, bundles = _service(record=record, agent_service=agents, trigger_service=triggers)

    with pytest.raises(BundleValidationError) as refused:
        await service.install(
            parse_bundle(CHANNEL.replace("instruction: x", "instruction: y")), {"bot": "t"}
        )

    assert [i.entity_key for i in refused.value.issues] == ["lead"]
    assert ("edit", "agent", lead_id) in permissions.asked
    assert agents.updates == []
    assert triggers.updates == []
    assert bundles.writes == []


async def test_a_failed_install_records_nothing_and_reraises():
    triggers = FakeTriggerSvc(fail_create=RuntimeError("scheduler down"))
    agents = FakeAgentSvc()
    service, bundles = _service(agent_service=agents, trigger_service=triggers)

    with pytest.raises(RuntimeError, match="scheduler down"):
        await service.install(parse_bundle(CRON), {})

    assert bundles.writes == []
    [created] = agents.calls
    assert len(agents.deleted) == 1
    assert created.name == "Lead"


async def test_a_failed_install_that_updated_nothing_leaves_the_previous_record_as_it_was():
    record, agents, triggers = _installed("lead", "inbox")
    before = deepcopy(record.install_result)
    triggers.fail_update = RuntimeError("db gone")
    service, bundles = _service(record=record, agent_service=agents, trigger_service=triggers)
    edited = CHANNEL.replace("agent: lead,", "agent: lead, prompt: hello,")

    with pytest.raises(RuntimeError, match="db gone"):
        await service.install(parse_bundle(edited), {})

    assert agents.updates == []
    assert bundles.writes == []
    assert record.install_result == before


async def test_a_redeploy_that_fails_after_updating_in_place_records_what_it_wrote():
    record, agents, triggers = _installed("lead", "inbox")
    triggers.fail_update = RuntimeError("db gone")
    service, bundles = _service(record=record, agent_service=agents, trigger_service=triggers)
    edited = CHANNEL.replace("instruction: x", "instruction: y").replace(
        "agent: lead,", "agent: lead, prompt: hello,"
    )

    with pytest.raises(RuntimeError, match="db gone"):
        await service.install(parse_bundle(edited), {})

    assert len(agents.updates) == 1
    [written] = bundles.writes
    assert written["status"] == "failed"
    entities = {e["key"]: e for e in written["install_result"]["entities"]}
    assert entities["lead"]["action"] == "updated"
    assert entities["inbox"]["id"] == record.install_result["entities"][1]["id"]


CATALOG = """
schema_version: "0.1.0"
name: pay
setup:
  - {key: signing, label: Signing, type: secret, required: true}
mcps:
  - {key: pay, name: Payments, catalog: ru.yookassa/mcp, context_secret: "${setup.signing}"}
agents: [{key: lead, name: Lead, model: m, instruction: x, mcps: [pay]}]
"""


async def test_an_unknown_catalog_mcp_blocks_before_any_write():
    agents = FakeAgentSvc()
    servers = FakeMcpServerSvc()
    service, bundles = _service(agent_service=agents, mcp_server_service=servers)

    with pytest.raises(BundleValidationError) as refused:
        await service.install(parse_bundle(CATALOG), {"signing": "s" * 40})

    assert str(refused.value).startswith(
        "package is not installable: mcp 'pay' names catalog server 'ru.yookassa/mcp'"
    )
    assert agents.calls == []
    assert bundles.writes == []


async def test_a_catalog_mcp_is_looked_up_once_per_service():
    spec = SimpleNamespace(
        id=uuid4(),
        json_spec={},
        remote_url="https://pay.example/mcp",
        cmd=None,
        docker_image_url=None,
    )
    servers = FakeMcpServerSvc({"ru.yookassa/mcp": spec})
    service, _ = _service(mcp_server_service=servers)

    preview = await service.analyze_bundle(parse_bundle(CATALOG), {"signing": "s" * 40})

    assert preview.installable
    assert servers.lookups == ["ru.yookassa/mcp"]
    found = await service.catalog_mcp("ru.yookassa/mcp")
    assert (found.spec_id, found.transport) == (str(spec.id), "url")
    assert servers.lookups == ["ru.yookassa/mcp"]


class EditableOnlyOnce(PermissionService):
    """Allows the plan's check, then refuses: the edit right was revoked before the write."""

    def __init__(self):
        self.asked = 0

    async def check(self, user_id, permission, resource_type, resource_id):
        self.asked += 1
        return self.asked == 1


async def test_the_installer_rechecks_edit_permission_right_before_an_update():
    record, agents, triggers = _installed("lead", "inbox")
    register_singleton(PermissionService, EditableOnlyOnce())
    service, _ = _service(record=record, agent_service=agents, trigger_service=triggers)

    with pytest.raises(BundleInstallError):
        await service.install(parse_bundle(CHANNEL.replace("instruction: x", "instruction: y")), {})

    assert agents.updates == []


async def test_a_stored_install_that_no_longer_validates_blocks_instead_of_duplicating():
    record = SimpleNamespace(id=uuid4(), canonical={"name": "tg", "bogus": 1}, install_result=None)
    service, bundles = _service(record=record)

    preview = await service.analyze_bundle(parse_bundle(CHANNEL))
    assert preview.installable is False
    assert any("tg" in i.message for i in preview.block_issues)

    with pytest.raises(BundleInstallError):
        await service.install(parse_bundle(CHANNEL), {"bot": "t"})
    assert bundles.writes == []
