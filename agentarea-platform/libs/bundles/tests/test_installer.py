"""Installer orchestration tests (mocked domain services)."""

import io
import json
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import pytest
from agentarea_agents.application import workspace_export_service
from agentarea_agents.application.skill_service import SkillService
from agentarea_agents.application.workspace_export_service import WorkspaceExportService
from agentarea_bundles.application.analyzer import (
    GITHUB_SKILL_NOT_APPLIED,
    BundleAnalyzer,
    PriorInstall,
    bundle_entities,
    parse_bundle,
)
from agentarea_bundles.application.installer import (
    BundleInstaller,
    BundleInstallError,
    BundleValidationError,
)
from agentarea_bundles.schemas.bundle import setup_refs
from agentarea_bundles.schemas.preview import EntityKind, EntityStatus
from agentarea_bundles.schemas.result import InstallAction, InstalledEntity, InstallResult
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.base.models import BaseModel
from agentarea_common.di.container import register_singleton
from agentarea_governance.application.catalog_install import CatalogInstallRefusedError
from agentarea_governance.domain.rules import PolicyEffect, PolicyRule, PolicySubjectType
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

FULL = """
schema_version: "0.1.0"
name: seo
setup:
  - {key: token, label: Token, type: secret, required: true}
mcps:
  - key: gh
    name: GitHub
    json_spec: {type: command, command: npx, args: ["-y", "@x/y"]}
    bindings: {GH_TOKEN: "${setup.token}"}
skills:
  - {key: sk, name: Audit, source_type: content, content: "# a"}
agents:
  - {key: lead, name: Lead, model: gpt-4o, instruction: x, mcps: [gh], skills: [sk]}
automations:
  - {key: daily, type: cron, cron: "0 9 * * *", agent: lead, prompt: go, enabled: false}
"""


def _by_id(known):
    return {str(k): v for k, v in (known or {}).items()}


class FakeMcpServerSvc:
    def __init__(self, catalog=None):
        self.calls = []
        self.catalog = catalog or {}
        self.catalog_lookups = []

    async def create_mcp_server(self, payload):
        self.calls.append(payload)
        return SimpleNamespace(id=uuid4())

    async def get_catalog_server(self, external_id):
        self.catalog_lookups.append(external_id)
        return self.catalog.get(external_id)


class FakeMcpInstSvc:
    def __init__(self, known=None):
        self.known = _by_id(known)
        self.calls = []
        self.created = []

    async def get(self, id):
        return self.known.get(str(id))

    async def create_instance(self, payload):
        self.calls.append(payload)
        instance = SimpleNamespace(id=uuid4())
        self.created.append(instance)
        return instance


class FakeSkillSvc:
    def __init__(self, known=None):
        self.known = _by_id(known)
        self.calls = []
        self.github_calls = []
        self.zips = []
        self.contents = []
        self.packages = []
        self.renames = []

    async def get(self, skill_id):
        return self.known.get(str(skill_id))

    async def create_from_content(self, payload):
        self.calls.append(payload)
        return SimpleNamespace(id=uuid4())

    async def create_from_github(self, payload):
        self.github_calls.append(payload)
        return SimpleNamespace(id=uuid4())

    async def create_from_zip(self, data, *, name):
        self.zips.append((data, name))
        return SimpleNamespace(id=uuid4())

    async def set_content(self, skill_id, content):
        self.contents.append((skill_id, content))
        return self.known.get(str(skill_id))

    async def replace_package_from_files(self, skill_id, files):
        self.packages.append((skill_id, files))
        return self.known.get(str(skill_id))

    async def update(self, skill_id, payload):
        self.renames.append((skill_id, payload))
        return self.known.get(str(skill_id))


class FakeAgentSvc:
    def __init__(self, known=None, approvals=None):
        self.known = _by_id(known)
        # {tool name -> ticked} the agent's approval rules set
        self.approvals = approvals or {}
        self.calls = []
        self.updates = []

    async def get(self, id):
        return self.known.get(str(id))

    async def get_with_skills(self, id):
        return self.known.get(str(id))

    async def with_approval_flags(self, agent_id, tools):
        flagged = []
        for tool in tools:
            if tool["name"] in self.approvals:
                settings = {**(tool.get("settings") or {})}
                settings["requires_user_confirmation"] = self.approvals[tool["name"]]
                tool = {**tool, "settings": settings}
            flagged.append(tool)
        return flagged

    async def create_agent(self, payload):
        self.calls.append(payload)
        return SimpleNamespace(id=uuid4())

    async def update_agent(self, id, payload):
        self.updates.append((id, payload))
        return self.known.get(str(id))


_CATALOG = {
    entry["slug"]: entry
    for entry in json.loads(
        (Path(__file__).parents[4] / "data" / "catalog" / "source-types.json").read_text()
    )["source_types"]
}


class FakeCatalogSession:
    """Answers CatalogSourceTypeRepository's lookups from the shipped catalog."""

    async def execute(self, statement, params=None):
        slug = (params or {}).get("slug")
        rows = [SimpleNamespace(external_id=slug, spec=_CATALOG[slug])] if slug in _CATALOG else []
        return SimpleNamespace(fetchall=lambda: rows)


class FakeStreamSvc:
    def __init__(self):
        self.repository_factory = SimpleNamespace(session=FakeCatalogSession())
        self.streams = []
        self.sources = []

    async def create_stream(self, *, name, description):
        stream = SimpleNamespace(id=uuid4(), name=name, description=description)
        self.streams.append(stream)
        return stream

    async def add_source(self, **kwargs):
        source = SimpleNamespace(id=uuid4(), **kwargs)
        self.sources.append(source)
        return source

    async def list_sources(self, stream_id):
        return [s for s in self.sources if s.stream_id == stream_id]


class FakeTriggerSvc:
    def __init__(self, known=None):
        self.known = _by_id(known)
        self.created = []
        self.disabled = []
        self.enabled = []
        self.updates = []
        self.stream_service = FakeStreamSvc()

    async def get_trigger(self, trigger_id):
        return self.known.get(str(trigger_id))

    async def create_trigger(self, domain):
        t = SimpleNamespace(id=uuid4(), name=domain.name)
        self.created.append(domain)
        return t

    async def update_trigger_from_payload(self, trigger_id, payload):
        self.updates.append((trigger_id, payload))
        return self.known.get(str(trigger_id))

    async def enable_trigger(self, trigger_id):
        self.enabled.append(trigger_id)
        return True

    async def disable_trigger(self, trigger_id):
        self.disabled.append(trigger_id)
        return True


class FakeTriggerRepo:
    def __init__(self, existing=None):
        self.existing = existing or []

    async def list_all(self):
        return self.existing


class FakeGovernanceSvc:
    def __init__(self, existing=None, known=None):
        self.existing = existing or []
        self.known = _by_id(known)
        self.created = []
        self.updates = []

    async def get_rule(self, *, rule_id):
        return self.known.get(str(rule_id))

    async def list_rules(self, **kwargs):
        return self.existing

    async def create_rule(self, *, rule):
        self.created.append(rule)
        return SimpleNamespace(id=uuid4())

    async def update_rule(self, *, rule_id, **fields):
        self.updates.append((rule_id, fields))
        return self.known.get(str(rule_id))


@pytest.fixture(autouse=True)
def _authz():
    register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())


def _installer(**overrides):
    deps = {
        "mcp_server_service": FakeMcpServerSvc(),
        "mcp_instance_service": FakeMcpInstSvc(),
        "skill_service": FakeSkillSvc(),
        "agent_service": FakeAgentSvc(),
        "trigger_service": FakeTriggerSvc(),
        "trigger_repository": FakeTriggerRepo(),
        "governance_service": FakeGovernanceSvc(),
        "user_context": UserContext(user_id="u", workspace_id="w", admin_workspaces=["w"]),
        "secret_manager": FakeSecretManager(),
    }
    deps.update(overrides)
    return BundleInstaller(**deps), deps


POLICIES = """
schema_version: "0.1.0"
name: pol
agents: [{key: lead, name: Lead, model: gpt-4o}]
policies:
  - {key: cap, subject: workspace, target: spend, effect: cap, params: {amount_usd: 50}}
  - {key: deny, subject: lead, target: "tool:send_email", effect: deny, message: no email}
"""


FULL_WITH_POLICY = (
    FULL
    + """policies:
  - {key: cap, subject: workspace, target: spend, effect: cap, params: {amount_usd: 50}}
"""
)


async def test_a_member_installing_policies_is_refused_before_anything_is_written():
    member = UserContext(user_id="u", workspace_id="w", admin_workspaces=[])
    inst, deps = _installer(user_context=member)

    with pytest.raises(HTTPException) as refused:
        await inst.install(parse_bundle(FULL_WITH_POLICY), {"token": "t"})

    assert refused.value.status_code == 403
    assert deps["mcp_server_service"].calls == []
    assert deps["mcp_instance_service"].calls == []
    assert deps["skill_service"].calls == []
    assert deps["agent_service"].calls == []
    assert deps["trigger_service"].created == []
    assert deps["governance_service"].created == []


async def test_a_member_installs_a_bundle_without_policies():
    member = UserContext(user_id="u", workspace_id="w", admin_workspaces=[])
    inst, deps = _installer(user_context=member)

    await inst.install(parse_bundle(FULL), {"token": "t"})

    assert len(deps["agent_service"].calls) == 1


async def test_an_automation_prompt_becomes_the_task_text():
    """The bundle schema calls it "task query passed to the agent on each run".

    It used to be written into the trigger's description, which the execution
    path then picked up because description stood in for a missing task text.
    With that stand-in gone the prompt has to land where the agent reads it.
    """
    inst, deps = _installer()
    await inst.install(parse_bundle(FULL), {"token": "t"})

    trigger = deps["trigger_service"].created[0]
    assert trigger.task_parameters["text"] == "go"


async def test_a_channel_prompt_becomes_the_task_text():
    """Same field, same mistake: it was stored under a key nothing reads."""
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: c\n'
        "agents: [{key: lead, name: Lead, model: gpt-4o}]\n"
        "channels:\n"
        "  - {key: tg, name: TG, type: telegram, agent: lead, prompt: Answer it}\n"
    )
    inst, deps = _installer()
    await inst.install(pkg, {})

    trigger = deps["trigger_service"].created[0]
    assert trigger.task_parameters["text"] == "Answer it"


async def test_policies_install_on_workspace_and_agent():
    inst, deps = _installer()
    res = await inst.install(parse_bundle(POLICIES), {})
    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("policy", "cap")] == InstallAction.CREATED
    assert actions[("policy", "deny")] == InstallAction.CREATED
    gov = deps["governance_service"]
    assert len(gov.created) == 2
    # workspace cap bound to workspace id; agent deny bound to the created agent id
    subjects = {str(r.subject_type): r.subject_id for r in gov.created}
    assert subjects["workspace"] == "w"
    # The human-readable reason is reported back, never written into params: the
    # typed param models forbid extras, so folding it in makes the rule fail the
    # enforceability check that guards this path.
    deny_rule = next(r for r in gov.created if r.effect.value == "deny")
    assert "message" not in deny_rule.params
    deny_entity = next(e for e in res.entities if e.key == "deny")
    assert "no email" in deny_entity.detail


def _assert_nothing_written(deps) -> None:
    assert deps["mcp_server_service"].calls == []
    assert deps["mcp_instance_service"].calls == []
    assert deps["skill_service"].calls == []
    assert deps["skill_service"].github_calls == []
    assert deps["agent_service"].calls == []
    assert deps["trigger_service"].created == []
    assert deps["governance_service"].created == []


async def test_unenforceable_policy_refuses_the_whole_install():
    # A spend cap the compiler cannot read (`period: day` — it knows month/run
    # only) would install as a row that silently never enforces. Analyze blocks
    # it, so install refuses it too, before the agent beside it is created.
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: p\n'
        "agents: [{key: lead, name: Lead, model: gpt-4o}]\npolicies:\n"
        "  - {key: daily, subject: workspace, target: spend, effect: cap, "
        "params: {amount_usd: 10, period: day}}\n"
    )
    inst, deps = _installer()
    with pytest.raises(BundleInstallError) as refused:
        await inst.install(pkg, {})
    assert any("daily" in issue.message for issue in refused.value.issues)
    _assert_nothing_written(deps)


async def test_policy_idempotent_when_rule_exists():
    same = SimpleNamespace(id=uuid4(), params={"amount_usd": 50}, condition=None)
    inst, deps = _installer(governance_service=FakeGovernanceSvc(existing=[same]))
    res = await inst.install(parse_bundle(POLICIES.split("  - {key: deny")[0]), {})
    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("policy", "cap")] == InstallAction.REUSED
    assert deps["governance_service"].created == []  # nothing created


async def test_a_rule_with_other_params_is_not_the_policy_and_one_is_created():
    bigger = SimpleNamespace(id=uuid4(), params={"amount_usd": 1000}, condition=None)
    inst, deps = _installer(governance_service=FakeGovernanceSvc(existing=[bigger]))
    res = await inst.install(parse_bundle(POLICIES.split("  - {key: deny")[0]), {})

    cap = next(e for e in res.entities if e.key == "cap")
    assert cap.action == InstallAction.CREATED
    [created] = deps["governance_service"].created
    assert created.params == {"amount_usd": 50}


async def test_policy_on_a_missing_agent_refuses_the_install():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: p
policies: [{key: orphan, subject: ghost, target: "*", effect: deny}]
"""
    )
    inst, deps = _installer()
    with pytest.raises(BundleInstallError):
        await inst.install(pkg, {})
    _assert_nothing_written(deps)


async def test_missing_required_setup_blocks_install():
    inst, _ = _installer()
    with pytest.raises(BundleInstallError):
        await inst.install(parse_bundle(FULL), setup_values={})  # token missing


async def test_full_install_creates_everything():
    inst, deps = _installer()
    res = await inst.install(parse_bundle(FULL), {"token": "secret"})
    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert all(a == InstallAction.CREATED for a in actions.values())
    # secret resolved into instance environment
    assert deps["mcp_instance_service"].calls[0].json_spec["environment"] == {"GH_TOKEN": "secret"}
    # agent wired to mcp by instance id + skill id
    agent = deps["agent_service"].calls[0]
    (instance,) = deps["mcp_instance_service"].created
    assert [(t.type, t.name) for t in agent.tools] == [("mcp", str(instance.id))]
    assert len(agent.skill_ids) == 1


async def test_disabled_automation_is_created_inactive():
    inst, deps = _installer()
    await inst.install(parse_bundle(FULL), {"token": "secret"})
    ts = deps["trigger_service"]
    assert [t.is_active for t in ts.created] == [False]
    assert ts.disabled == []


async def test_enabled_automation_is_created_active():
    pkg = parse_bundle(FULL.replace("enabled: false", "enabled: true"))
    inst, deps = _installer()
    await inst.install(pkg, {"token": "secret"})
    assert [t.is_active for t in deps["trigger_service"].created] == [True]
    assert deps["trigger_service"].disabled == []


class FakeSecretManager:
    def __init__(self, secrets=None):
        self.secrets: dict[str, str] = dict(secrets or {})

    async def set_secret(self, name, value):
        self.secrets[name] = value

    async def get_secret(self, name):
        return self.secrets.get(name)

    async def delete_secret(self, name):
        self.secrets.pop(name, None)


CHANNEL = """
schema_version: "0.1.0"
name: tg
setup:
  - {key: bot, label: Bot Token, type: secret, required: true}
agents: [{key: lead, name: Lead, model: gpt-4o}]
channels:
  - {key: inbox, type: telegram, name: TG Inbox, agent: lead, bindings: {bot_token: "${setup.bot}"}, enabled: false}
"""


async def test_channel_installs_a_stream_its_source_and_a_trigger_and_stores_the_secret():
    sm = FakeSecretManager()
    inst, deps = _installer(secret_manager=sm)
    res = await inst.install(parse_bundle(CHANNEL), {"bot": "12345:secret"})

    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("channel", "inbox")] == InstallAction.CREATED

    ts = deps["trigger_service"]
    (stream,) = ts.stream_service.streams
    (source,) = ts.stream_service.sources
    assert stream.name == "tg:inbox"
    assert source.stream_id == stream.id
    assert source.source_type == "telegram"

    # a stream trigger on that stream, imported disabled
    assert len(ts.created) == 1
    assert ts.created[0].name == "tg:inbox"
    assert ts.created[0].stream_id == stream.id
    assert ts.created[0].is_active is False
    assert ts.disabled == []

    # the bot token is stored under the source's credential key, with the
    # webhook secret the catalog entry issues
    assert list(sm.secrets) == [f"channel_cred:telegram:{source.id}"]
    stored = json.loads(sm.secrets[f"channel_cred:telegram:{source.id}"])
    assert stored["bot_token"] == "12345:secret"  # noqa: S105
    assert stored["secret_token"]


async def test_a_generic_channel_is_a_generic_webhook_source_with_an_issued_secret():
    sm = FakeSecretManager()
    inst, deps = _installer(secret_manager=sm)
    pkg = parse_bundle(CHANNEL.replace("type: telegram", "type: generic"))
    await inst.install(pkg, {"bot": "x"})

    (source,) = deps["trigger_service"].stream_service.sources
    assert source.source_type == "generic_webhook"
    (stored,) = sm.secrets.values()
    assert json.loads(stored)["signing_secret"]


async def test_a_channel_type_the_catalog_lacks_refuses_the_install(monkeypatch):
    monkeypatch.setitem(globals(), "_CATALOG", {})
    inst, deps = _installer(secret_manager=FakeSecretManager())
    with pytest.raises(BundleInstallError):
        await inst.install(parse_bundle(CHANNEL), {"bot": "x"})
    assert deps["trigger_service"].created == []


async def test_channel_on_a_missing_agent_refuses_the_install():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: tg
channels:
  - {key: inbox, type: telegram, name: TG, agent: ghost, bindings: {}, enabled: false}
"""
    )
    inst, deps = _installer()
    with pytest.raises(BundleInstallError):
        await inst.install(pkg, {})
    _assert_nothing_written(deps)


def _reused_before():
    """An earlier install of FULL that linked what it found: its record, and those entities."""
    skill = SimpleNamespace(id=uuid4())
    agent = SimpleNamespace(id=uuid4(), status="active")
    instance = SimpleNamespace(id=uuid4())
    trigger = SimpleNamespace(id=uuid4(), name="seo:daily", agent_id=agent.id)
    prior = PriorInstall(
        bundle=parse_bundle(FULL),
        result=InstallResult(
            bundle_name="seo",
            entities=[
                InstalledEntity(
                    kind=kind, key=key, name=key, action=InstallAction.REUSED, id=str(i)
                )
                for kind, key, i in (
                    (EntityKind.MCP, "gh", instance.id),
                    (EntityKind.SKILL, "sk", skill.id),
                    (EntityKind.AGENT, "lead", agent.id),
                )
            ],
        ),
    )
    services = {
        "skill_service": FakeSkillSvc(known={skill.id: skill}),
        "agent_service": FakeAgentSvc(known={agent.id: agent}),
        "mcp_instance_service": FakeMcpInstSvc(known={instance.id: instance}),
        "trigger_repository": FakeTriggerRepo(existing=[trigger]),
    }
    return prior, services, skill, agent, instance, trigger


async def test_a_reinstall_links_what_the_earlier_install_reused_by_its_id():
    prior, services, skill, agent, instance, trigger = _reused_before()
    inst, deps = _installer(**services)
    res = await inst.install(parse_bundle(FULL), {"token": "secret"}, prior=prior)
    ids = {(e.kind, e.key): (e.action, e.id) for e in res.entities}
    assert ids[("mcp", "gh")] == (InstallAction.REUSED, str(instance.id))
    assert ids[("skill", "sk")] == (InstallAction.REUSED, str(skill.id))
    assert ids[("agent", "lead")] == (InstallAction.REUSED, str(agent.id))
    assert ids[("automation", "daily")] == (InstallAction.REUSED, str(trigger.id))
    assert deps["agent_service"].calls == []
    assert deps["agent_service"].updates == []
    assert deps["skill_service"].calls == []
    assert deps["mcp_instance_service"].calls == []
    assert deps["trigger_service"].created == []


async def test_a_namesake_the_bundle_did_not_install_is_never_reused():
    # Entities carrying the bundle's names, put there by someone else: no
    # install recorded them, so this one creates its own.
    _, services, _, agent, _, _ = _reused_before()
    inst, deps = _installer(**services)
    res = await inst.install(parse_bundle(FULL), {"token": "secret"})

    assert {e.action for e in res.entities} == {InstallAction.CREATED}
    (created,) = deps["agent_service"].calls
    (new_instance,) = deps["mcp_instance_service"].created
    assert [t.name for t in created.tools] == [str(new_instance.id)]
    (cron,) = deps["trigger_service"].created
    assert cron.agent_id != agent.id


async def test_a_trigger_under_the_bundle_name_running_another_agent_is_not_reused():
    prior, services, _, agent, _, _ = _reused_before()
    squatter = SimpleNamespace(id=uuid4(), name="seo:daily", agent_id=uuid4())
    services["trigger_repository"] = FakeTriggerRepo(existing=[squatter])
    inst, deps = _installer(**services)
    res = await inst.install(parse_bundle(FULL), {"token": "secret"}, prior=prior)

    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("automation", "daily")] == InstallAction.CREATED
    (cron,) = deps["trigger_service"].created
    assert cron.agent_id == agent.id


async def test_a_trigger_other_than_the_recorded_one_is_not_reused():
    # A member who may run the bundle's agent adds a trigger under the bundle's
    # name for it: the install recorded another one, so it is not the bundle's.
    prior, services, *_ = _reused_before()
    recorded = InstalledEntity(
        kind=EntityKind.AUTOMATION,
        key="daily",
        name="seo:daily",
        action=InstallAction.REUSED,
        id=str(uuid4()),
    )
    prior.result.entities.append(recorded)
    inst, _ = _installer(**services)
    res = await inst.install(parse_bundle(FULL), {"token": "secret"}, prior=prior)

    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("automation", "daily")] == InstallAction.CREATED


async def test_a_recorded_agent_since_archived_is_installed_again():
    prior, services, _, agent, instance, _ = _reused_before()
    agent.status = "archived"
    inst, deps = _installer(**services)
    res = await inst.install(parse_bundle(FULL), {"token": "secret"}, prior=prior)

    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("agent", "lead")] == InstallAction.CREATED
    assert actions[("skill", "sk")] == InstallAction.REUSED
    (created,) = deps["agent_service"].calls
    assert [t.name for t in created.tools] == [str(instance.id)]


async def test_unsupported_mcp_skipped_and_agent_created_without_it():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: p
mcps:
  - {key: bad, name: Bad, json_spec: {type: command, command: "./bin/x"}}
agents: [{key: a, name: A, model: gpt-4o, mcps: [bad]}]
"""
    )
    inst, deps = _installer()
    res = await inst.install(pkg, {})
    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("mcp", "bad")] == InstallAction.SKIPPED
    # agent created with no tools (unsupported mcp dropped)
    assert deps["agent_service"].calls[0].tools == []


async def test_agent_toolsets_become_code_tools():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: p
agents:
  - {key: a, name: A, model: gpt-4o, toolsets: [agentarea/shell, agentarea/files]}
"""
    )
    inst, deps = _installer()
    await inst.install(pkg, {})
    tools = deps["agent_service"].calls[0].tools
    assert [(t.type, t.name) for t in tools] == [
        ("code", "agentarea/shell"),
        ("code", "agentarea/files"),
    ]


async def test_exported_workspace_bundle_installs_agent_skill_and_disabled_triggers(
    monkeypatch,
):
    source_workspace_id = "source"
    source_context = UserContext(
        user_id="source-user",
        workspace_id=source_workspace_id,
        admin_workspaces=[source_workspace_id],
    )
    skill = SimpleNamespace(
        id=uuid4(),
        workspace_id=source_workspace_id,
        registry_item_id=None,
        is_catalog=False,
        slug="daily-skill",
        name="Daily Skill",
        description="",
        content="# Daily Skill",
        source_type="content",
        source_url=None,
    )
    agent = SimpleNamespace(
        id=uuid4(),
        workspace_id=source_workspace_id,
        registry_item_id=None,
        is_catalog=False,
        slug="daily-agent",
        name="Daily Agent",
        description="",
        instruction="Summarize the workspace.",
        model_id="gpt-4o",
        tools=[{"type": "code", "name": "agentarea/shell"}],
        skills=[skill],
        planning=None,
        a2ui_enabled=None,
    )
    cron = SimpleNamespace(
        id=uuid4(),
        name="nightly-summary",
        trigger_type="cron",
        agent_id=agent.id,
        cron_expression="0 0 * * *",
        timezone="UTC",
        task_parameters={"text": "Prepare the nightly summary."},
        is_active=False,
        conditions={},
    )
    stream_trigger = SimpleNamespace(
        id=uuid4(),
        name="incoming-events",
        trigger_type="stream",
        agent_id=agent.id,
        task_parameters={"text": "Process the inbound event."},
        is_active=False,
        conditions={},
    )
    agent_service = SimpleNamespace(
        list=AsyncMock(return_value=[agent]),
        get_with_skills=AsyncMock(return_value=agent),
    )
    skill_service = SimpleNamespace(
        list=AsyncMock(return_value=[skill]),
        read_skill_md=AsyncMock(return_value=skill.content),
    )
    trigger_repository = SimpleNamespace(list_all=AsyncMock(return_value=[cron, stream_trigger]))
    monkeypatch.setattr(
        workspace_export_service,
        "load_workspace",
        AsyncMock(
            return_value=SimpleNamespace(
                id=source_workspace_id,
                name="Source workspace",
                slug="source-workspace",
            )
        ),
        raising=False,
    )

    export_service = WorkspaceExportService(
        agent_service=agent_service,
        repository_factory=SimpleNamespace(user_context=source_context),
        skill_service=skill_service,
        trigger_repository=trigger_repository,
    )
    yaml_text = await export_service.export_workspace()
    package = parse_bundle(yaml_text)
    preview = await BundleAnalyzer().analyze(package)

    assert preview.installable
    assert preview.issues == []
    assert package.name == "source-workspace"
    assert package.display_name == "Source workspace"
    assert package.agents[0].skills == [package.skills[0].key]
    assert package.agents[0].toolsets == ["agentarea/shell"]

    model_setup = next(field for field in package.setup if field.label == "Model for Daily Agent")
    assert package.agents[0].model == f"${{setup.{model_setup.key}}}"
    assert model_setup.type.value == "string"
    assert len(package.automations) == 1
    assert package.automations[0].enabled is False
    # A stream trigger's sources live on its stream, which bundles do not carry.
    assert package.channels == []

    target_context = UserContext(
        user_id="target-user",
        workspace_id="target",
        admin_workspaces=["target"],
    )
    installer, deps = _installer(user_context=target_context)
    result = await installer.install(package, {model_setup.key: "gpt-4o"})

    assert {entity.action for entity in result.entities} == {InstallAction.CREATED}
    assert len(deps["skill_service"].calls) == 1
    assert deps["agent_service"].calls[0].model_id == "gpt-4o"
    assert len(deps["agent_service"].calls) == 1
    (cron_created,) = deps["trigger_service"].created
    assert cron_created.task_parameters == {"text": "Prepare the nightly summary."}
    assert cron_created.cron_expression == "0 0 * * *"
    assert cron_created.timezone == "UTC"
    assert cron_created.is_active is False
    assert deps["trigger_service"].disabled == []


async def test_exported_workspace_round_trips_a_uuid_referenced_mcp_with_a_credentialed_arg(
    monkeypatch,
):
    source_context = UserContext(
        user_id="source-user", workspace_id="source", admin_workspaces=["source"]
    )
    instance = SimpleNamespace(
        id=uuid4(),
        workspace_id="source",
        registry_item_id=None,
        is_catalog=False,
        name="Postgres",
        server_spec_id=str(uuid4()),
        json_spec={},
        get_configured_env_vars=lambda: [],
    )
    agent = SimpleNamespace(
        id=uuid4(),
        workspace_id="source",
        registry_item_id=None,
        is_catalog=False,
        name="Analyst",
        instruction="Answer from the database.",
        # The webapp attaches an MCP by instance id, not by name.
        tools=[{"type": "mcp", "name": str(instance.id)}],
        skills=[],
    )
    mcp_instance_service = SimpleNamespace(
        list=AsyncMock(return_value=[instance]),
        get_transport_spec_for_instance=AsyncMock(
            return_value={
                "type": "command",
                "command": "npx",
                "args": [
                    "-y",
                    "@modelcontextprotocol/server-postgres",
                    "postgresql://app:SOURCE_PASSWORD@db.source:5432/app",  # pragma: allowlist secret
                ],
                "environment": {"PGAPPNAME": "agentarea"},
            }
        ),
    )
    monkeypatch.setattr(
        workspace_export_service,
        "load_workspace",
        AsyncMock(return_value=SimpleNamespace(id="source", name="Source", slug="source")),
        raising=False,
    )
    export_service = WorkspaceExportService(
        agent_service=SimpleNamespace(
            list=AsyncMock(return_value=[agent]),
            get_with_skills=AsyncMock(return_value=agent),
        ),
        repository_factory=SimpleNamespace(user_context=source_context),
        mcp_instance_service=mcp_instance_service,
    )

    yaml_text = await export_service.export_workspace()
    package = parse_bundle(yaml_text)
    preview = await BundleAnalyzer().analyze(package)

    assert "SOURCE_PASSWORD" not in yaml_text
    assert preview.installable
    assert preview.issues == []
    assert package.agents[0].mcps == [package.mcps[0].key]

    (dsn_key,) = setup_refs(package.mcps[0].json_spec["args"][2])
    model_key = next(f.key for f in package.setup if f.label == "Model for Analyst")
    target_dsn = "postgresql://app:TARGET_PASSWORD@db.target:5432/app"  # pragma: allowlist secret
    installer, deps = _installer(
        user_context=UserContext(user_id="t", workspace_id="target", admin_workspaces=["target"])
    )
    result = await installer.install(package, {dsn_key: target_dsn, model_key: "gpt-4o"})

    assert {entity.action for entity in result.entities} == {InstallAction.CREATED}
    spec = deps["mcp_server_service"].calls[0]
    assert spec.cmd == ["npx", "-y", "@modelcontextprotocol/server-postgres", target_dsn]
    assert {"name": "PGAPPNAME", "isSecret": False} in [
        {"name": entry["name"], "isSecret": entry["isSecret"]} for entry in spec.env_schema
    ]
    created_instance = deps["mcp_instance_service"].calls[0]
    assert created_instance.json_spec["environment"] == {"PGAPPNAME": "agentarea"}
    tools = deps["agent_service"].calls[0].tools
    (instance,) = deps["mcp_instance_service"].created
    assert [(tool.type, tool.name) for tool in tools] == [("mcp", str(instance.id))]


async def test_a_json_spec_reference_to_an_undeclared_setup_field_blocks_install():
    package = parse_bundle(
        """
schema_version: "0.1.0"
name: p
mcps:
  - key: db
    name: DB
    json_spec: {type: command, command: npx, args: ["-y", "pg", "${setup.missing}"]}
"""
    )

    preview = await BundleAnalyzer().analyze(package)

    assert not preview.installable
    assert "missing" in preview.issues[0].message


async def test_github_skill_is_imported_from_its_repository():
    package = parse_bundle(
        """
schema_version: "0.1.0"
name: p
skills:
  - {key: review, name: Review, source_type: github, source_url: "https://github.com/o/r/tree/main/review"}
agents: [{key: a, name: A, model: gpt-4o, skills: [review]}]
"""
    )
    installer, deps = _installer()

    result = await installer.install(package, {})

    actions = {(e.kind, e.key): e.action for e in result.entities}
    assert actions[("skill", "review")] == InstallAction.CREATED
    (call,) = deps["skill_service"].github_calls
    assert call.github_url == "https://github.com/o/r/tree/main/review"
    assert call.name == "Review"
    assert len(deps["agent_service"].calls[0].skill_ids) == 1


async def test_a_github_skill_is_refused_when_the_install_policy_denies_community_sources():
    caller = UserContext(user_id="u", workspace_id="w", admin_workspaces=["w"])
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: BaseModel.metadata.create_all(c, tables=[PolicyRuleORM.__table__])
        )
    async with async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)() as s:
        await PolicyRuleRepository(s, caller).create(
            PolicyRule(
                subject_type=PolicySubjectType.WORKSPACE,
                subject_id=caller.workspace_id,
                target="registry_trust:community",
                effect=PolicyEffect.DENY,
            )
        )
        await s.commit()
        package = parse_bundle(
            """
schema_version: "0.1.0"
name: p
skills:
  - {key: review, name: Review, source_type: github, source_url: "https://github.com/o/r"}
agents: [{key: a, name: A, model: gpt-4o, skills: [review]}]
"""
        )
        installer, deps = _installer(
            skill_service=SkillService(SimpleNamespace(session=s, user_context=caller), caller),
            user_context=caller,
        )

        with pytest.raises(CatalogInstallRefusedError, match="registry_trust:community"):
            await installer.install(package, {})

    await engine.dispose()
    assert deps["agent_service"].calls == []


BLOCKED = """
schema_version: "0.1.0"
name: b6
agents:
  - {key: a1, name: nomodel, skills: [missing], mcps: [nope]}
automations:
  - {key: c, cron: "0 9 * * *", agent: ghost, prompt: x}
"""


async def test_a_bundle_analyze_blocks_is_refused_by_install_before_anything_is_written():
    pkg = parse_bundle(BLOCKED)
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False

    inst, deps = _installer()
    with pytest.raises(BundleInstallError) as refused:
        await inst.install(pkg, {})

    assert {i.message for i in refused.value.issues} == {i.message for i in preview.block_issues}
    _assert_nothing_written(deps)


async def test_duplicate_entity_keys_are_refused_by_install():
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: b4\nskills:\n'
        "  - {key: s1, name: dup, content: hi}\n"
        "  - {key: s1, name: dup2, content: hi}\n"
    )
    inst, deps = _installer()
    with pytest.raises(BundleInstallError) as refused:
        await inst.install(pkg, {})

    assert any("duplicate skill key 's1'" in i.message for i in refused.value.issues)
    _assert_nothing_written(deps)


class _Deleting:
    """Records deletes made by a failed install's compensation."""

    def __init__(self):
        self.deleted: list[tuple[str, object]] = []


def _compensating_installer(**overrides):
    log = _Deleting()

    class Specs(FakeMcpServerSvc):
        async def delete_mcp_server(self, id):
            log.deleted.append(("spec", id))
            return True

    class Instances(FakeMcpInstSvc):
        async def delete_instance(self, id):
            log.deleted.append(("instance", id))
            return True

    class Skills(FakeSkillSvc):
        async def delete(self, skill_id):
            log.deleted.append(("skill", skill_id))
            return True

    deps = {
        "mcp_server_service": Specs(),
        "mcp_instance_service": Instances(),
        "skill_service": Skills(),
    }
    deps.update(overrides)
    inst, all_deps = _installer(**deps)
    return inst, all_deps, log


async def test_a_failed_install_removes_what_it_created_so_a_retry_starts_clean():
    class FailingAgents(FakeAgentSvc):
        async def create_agent(self, payload):
            raise RuntimeError("database went away")

    inst, _deps, log = _compensating_installer(agent_service=FailingAgents())

    with pytest.raises(RuntimeError):
        await inst.install(parse_bundle(FULL), {"token": "t"})

    # newest first: skill, then the MCP instance, then its spec
    assert [kind for kind, _ in log.deleted] == ["skill", "instance", "spec"]


async def test_an_invalid_skill_at_install_is_a_validation_error_and_leaves_nothing():
    class RefusingSkills(FakeSkillSvc):
        async def create_from_content(self, payload):
            raise ValueError("Failed to parse skill content: mapping values are not allowed")

        async def delete(self, skill_id):
            raise AssertionError("nothing was created")

    inst, deps, log = _compensating_installer(skill_service=RefusingSkills())

    with pytest.raises(BundleValidationError, match=r"skill 'sk' is not a valid SKILL\.md"):
        await inst.install(parse_bundle(FULL), {"token": "t"})

    assert [kind for kind, _ in log.deleted] == ["instance", "spec"]
    assert deps["agent_service"].calls == []


async def test_a_reused_entity_is_never_removed_by_a_failed_install():
    class FailingAgents(FakeAgentSvc):
        async def create_agent(self, payload):
            raise RuntimeError("boom")

    existing = SimpleNamespace(id=uuid4())
    inst, deps, log = _compensating_installer(agent_service=FailingAgents())
    deps["mcp_instance_service"].known = {str(existing.id): existing}
    prior = PriorInstall(
        bundle=parse_bundle(FULL),
        result=InstallResult(
            bundle_name="seo",
            entities=[
                InstalledEntity(
                    kind=EntityKind.MCP,
                    key="gh",
                    name="GitHub",
                    action=InstallAction.REUSED,
                    id=str(existing.id),
                )
            ],
        ),
    )

    with pytest.raises(RuntimeError):
        await inst.install(parse_bundle(FULL), {"token": "t"}, prior=prior)

    assert [kind for kind, _ in log.deleted] == ["skill"]


SIGNED = """
schema_version: "0.1.0"
name: app
setup:
  - {key: bearer, label: Bearer, type: secret, required: true}
  - {key: signing, label: Signing key, type: secret, required: true}
mcps:
  - key: tools
    name: App tools
    json_spec: {type: url, endpoint_url: "https://app.example/mcp"}
    bindings: {Authorization: "Bearer ${setup.bearer}"}
    context_secret: "${setup.signing}"
"""


async def test_a_bundle_sets_the_context_secret_of_a_url_mcp_from_setup():
    inst, deps = _installer()
    signing = "s" * 40

    await inst.install(parse_bundle(SIGNED), {"bearer": "b", "signing": signing})

    (created,) = deps["mcp_instance_service"].calls
    assert created.context_secret == signing
    assert "s" * 40 not in str(created.json_spec)


async def test_a_short_context_secret_is_refused_without_echoing_it():
    inst, deps = _installer()

    with pytest.raises(BundleValidationError) as refused:
        await inst.install(parse_bundle(SIGNED), {"bearer": "b", "signing": "too-short-value"})

    assert "too-short-value" not in str(refused.value)
    assert "setup field 'signing'" in str(refused.value)
    _assert_nothing_written(deps)


# -- redeploy: upsert against the previous install ----------------------------

DEPLOYED = """
schema_version: "0.1.0"
name: seo
setup:
  - {key: bot, label: Bot, type: secret}
mcps:
  - {key: gh, name: GitHub, json_spec: {type: command, command: npx, args: ["-y", "gh"]}}
skills:
  - {key: sk, name: Audit, source_type: content, content: "# a"}
agents:
  - {key: lead, name: Lead, model: gpt-4o, instruction: x, mcps: [gh], skills: [sk]}
channels:
  - {key: inbox, name: Inbox, agent: lead, bindings: {bot_token: "${setup.bot}"}, prompt: hi}
automations:
  - {key: daily, type: cron, cron: "0 9 * * *", agent: lead, prompt: go}
policies:
  - {key: cap, subject: workspace, target: spend, effect: cap, params: {amount_usd: 50}}
"""

_KINDS = (
    (EntityKind.MCP, "gh", "GitHub"),
    (EntityKind.SKILL, "sk", "Audit"),
    (EntityKind.AGENT, "lead", "Lead"),
    (EntityKind.CHANNEL, "inbox", "seo:inbox"),
    (EntityKind.AUTOMATION, "daily", "seo:daily"),
    (EntityKind.POLICY, "cap", "cap"),
)


async def _may_edit_anything(kind, entity_id):
    return True


def _every(pkg):
    """Approve an update of every key, as a plan that updates everything would."""
    return {(kind, item.key) for kind in EntityKind for item in bundle_entities(pkg, kind)}


def _deployed(action=InstallAction.CREATED, text=DEPLOYED):
    """A previous install of ``text``: its prior record plus the services that know its ids.

    ``ids["credentials"]`` is where the inbox channel's source keeps its credentials.
    """
    ids = {key: uuid4() for _, key, _ in _KINDS}
    stream_id, credential_key = uuid4(), uuid4()
    ids["credentials"] = f"channel_cred:telegram:{credential_key}"
    prior = PriorInstall(
        bundle=parse_bundle(text),
        result=InstallResult(
            bundle_name="seo",
            entities=[
                InstalledEntity(kind=kind, key=key, name=name, action=action, id=str(ids[key]))
                for kind, key, name in _KINDS
            ],
        ),
    )

    def entity(key, **fields):
        return {ids[key]: SimpleNamespace(id=ids[key], **fields)}

    agents = FakeAgentSvc(known=entity("lead", name="Lead", status="active", tools=[], skills=[]))

    triggers = FakeTriggerSvc(
        known={
            **entity("inbox", name="seo:inbox", is_active=False, stream_id=stream_id),
            **entity("daily", name="seo:daily", is_active=False),
        }
    )
    triggers.stream_service.sources.append(
        SimpleNamespace(
            id=uuid4(), stream_id=stream_id, webhook_type="telegram", credential_key=credential_key
        )
    )
    services = {
        "mcp_instance_service": FakeMcpInstSvc(known=entity("gh", name="GitHub")),
        "skill_service": FakeSkillSvc(known=entity("sk", name="Audit")),
        "agent_service": agents,
        "trigger_service": triggers,
        "governance_service": FakeGovernanceSvc(known=entity("cap")),
        "may_edit": _may_edit_anything,
    }
    return prior, ids, services


async def test_redeploy_of_the_same_bundle_changes_nothing():
    prior, _, services = _deployed()
    inst, deps = _installer(**services)

    res = await inst.install(parse_bundle(DEPLOYED), {}, prior=prior)

    assert {e.action for e in res.entities} == {InstallAction.UNCHANGED}
    assert deps["agent_service"].calls == []
    assert deps["agent_service"].updates == []
    assert deps["skill_service"].calls == []
    assert deps["skill_service"].contents == []
    assert deps["trigger_service"].created == []
    assert deps["trigger_service"].updates == []
    assert deps["governance_service"].created == []
    assert deps["governance_service"].updates == []
    assert deps["mcp_instance_service"].calls == []


async def test_redeploy_updates_an_edited_agent_through_the_agent_service():
    prior, ids, services = _deployed()
    inst, deps = _installer(**services)
    edited = DEPLOYED.replace("instruction: x", "instruction: y").replace(
        "model: gpt-4o,", "model: gpt-5, description: Leads,"
    )

    pkg = parse_bundle(edited)
    res = await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    [(agent_id, payload)] = deps["agent_service"].updates
    assert agent_id == ids["lead"]
    assert payload.instruction == "y"
    assert payload.model_id == "gpt-5"
    assert payload.description == "Leads"
    assert [(t.type, t.name) for t in payload.tools] == [("mcp", str(ids["gh"]))]
    assert payload.skill_ids == [ids["sk"]]
    assert deps["agent_service"].calls == []
    actions = {e.key: e.action for e in res.entities}
    assert actions["lead"] == InstallAction.UPDATED
    assert actions["sk"] == InstallAction.UNCHANGED


async def test_redeploy_rewrites_an_edited_skill():
    prior, ids, services = _deployed()
    inst, deps = _installer(**services)

    pkg = parse_bundle(DEPLOYED.replace('content: "# a"', 'content: "# b"'))
    res = await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    # The whole package is replaced, so a file the folder no longer holds goes.
    assert deps["skill_service"].packages == [(ids["sk"], {"SKILL.md": "# b"})]
    assert deps["skill_service"].contents == []
    assert deps["skill_service"].calls == []
    assert next(e for e in res.entities if e.key == "sk").action == InstallAction.UPDATED


async def test_redeploy_updates_an_automation_and_its_enabled_state():
    prior, ids, services = _deployed()
    inst, deps = _installer(**services)
    edited = DEPLOYED.replace(
        'cron: "0 9 * * *", agent: lead, prompt: go',
        'cron: "0 10 * * *", timezone: Europe/Berlin, agent: lead, prompt: go now, enabled: true',
    )

    pkg = parse_bundle(edited)
    res = await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    ts = deps["trigger_service"]
    [(trigger_id, payload)] = ts.updates
    assert trigger_id == ids["daily"]
    assert payload.cron_expression == "0 10 * * *"
    assert payload.timezone == "Europe/Berlin"
    assert payload.task_parameters == {"text": "go now"}
    assert payload.agent_id == ids["lead"]
    assert ts.enabled == [ids["daily"]]
    assert ts.created == []
    assert next(e for e in res.entities if e.key == "daily").action == InstallAction.UPDATED


async def test_redeploy_updates_a_channel_and_writes_its_credentials_to_its_source():
    prior, ids, services = _deployed()
    sm = FakeSecretManager()
    inst, deps = _installer(**services, secret_manager=sm)

    pkg = parse_bundle(DEPLOYED.replace("prompt: hi", "prompt: hello"))
    res = await inst.install(pkg, {"bot": "new"}, prior=prior, approved_updates=_every(pkg))

    [(trigger_id, payload)] = deps["trigger_service"].updates
    assert trigger_id == ids["inbox"]
    assert payload.task_parameters == {"text": "hello"}
    assert payload.description == "Inbox"
    assert sm.secrets == {ids["credentials"]: '{"bot_token": "new"}'}
    assert next(e for e in res.entities if e.key == "inbox").action == InstallAction.UPDATED


async def test_a_redeploy_without_the_secret_leaves_credentials_alone():
    prior, ids, services = _deployed()
    sm = FakeSecretManager({ids["credentials"]: '{"bot_token": "old"}'})
    inst, deps = _installer(**services, secret_manager=sm)

    pkg = parse_bundle(DEPLOYED.replace("prompt: hi", "prompt: hello"))
    res = await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    assert len(deps["trigger_service"].updates) == 1
    assert sm.secrets == {ids["credentials"]: '{"bot_token": "old"}'}
    assert next(e for e in res.entities if e.key == "inbox").action == InstallAction.UPDATED


async def test_a_supplied_secret_is_merged_into_the_stored_credentials():
    prior, ids, services = _deployed()
    sm = FakeSecretManager({ids["credentials"]: '{"bot_token": "old", "secret_token": "kept"}'})
    inst, deps = _installer(**services, secret_manager=sm)

    pkg = parse_bundle(DEPLOYED)
    res = await inst.install(pkg, {"bot": "new"}, prior=prior, approved_updates=_every(pkg))

    assert deps["trigger_service"].updates == []
    assert json.loads(sm.secrets[ids["credentials"]]) == {
        "bot_token": "new",
        "secret_token": "kept",
    }
    assert next(e for e in res.entities if e.key == "inbox").action == InstallAction.UPDATED


CHAT = DEPLOYED.replace(
    "setup:\n", 'setup:\n  - {key: chat, label: Chat, default: "42"}\n'
).replace(
    'bindings: {bot_token: "${setup.bot}"}',
    'bindings: {bot_token: "${setup.bot}", chat_id: "${setup.chat}"}',
)


async def test_a_channel_whose_stored_credentials_lack_every_bound_key_gets_all_of_them():
    prior, ids, services = _deployed(text=CHAT)
    sm = FakeSecretManager({ids["credentials"]: '{"secret_token": "kept"}'})
    inst, _ = _installer(**services, secret_manager=sm)

    pkg = parse_bundle(CHAT)
    await inst.install(pkg, {"bot": "new"}, prior=prior, approved_updates=_every(pkg))

    assert json.loads(sm.secrets[ids["credentials"]]) == {
        "secret_token": "kept",
        "bot_token": "new",
        "chat_id": "42",
    }


async def test_a_channel_with_stored_credentials_gets_only_the_supplied_ones():
    prior, ids, services = _deployed(text=CHAT)
    sm = FakeSecretManager({ids["credentials"]: '{"bot_token": "old", "chat_id": "7"}'})
    inst, _ = _installer(**services, secret_manager=sm)

    pkg = parse_bundle(CHAT)
    await inst.install(pkg, {"bot": "new"}, prior=prior, approved_updates=_every(pkg))

    assert json.loads(sm.secrets[ids["credentials"]]) == {"bot_token": "new", "chat_id": "7"}


async def test_an_unresolved_placeholder_is_never_written_as_a_credential():
    sm = FakeSecretManager()
    inst, deps = _installer(secret_manager=sm)

    bound = DEPLOYED.replace(
        'args: ["-y", "gh"]}}', 'args: ["-y", "gh"]}, bindings: {GH_TOKEN: "${setup.bot}"}}'
    )
    await inst.install(parse_bundle(bound), {}, prior=None)

    (stored,) = sm.secrets.values()
    assert "bot_token" not in json.loads(stored)
    assert "${setup" not in stored
    assert "${setup" not in json.dumps([c.json_spec for c in deps["mcp_instance_service"].calls])


async def test_an_unresolved_placeholder_is_never_written_on_a_redeploy():
    prior, ids, services = _deployed()
    sm = FakeSecretManager({ids["credentials"]: '{"secret_token": "kept"}'})
    inst, _ = _installer(**services, secret_manager=sm)

    pkg = parse_bundle(DEPLOYED)
    await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    assert sm.secrets == {ids["credentials"]: '{"secret_token": "kept"}'}


async def test_a_redeploy_does_not_demand_secrets_it_does_not_write():
    required = DEPLOYED.replace(
        "{key: bot, label: Bot, type: secret}",
        "{key: bot, label: Bot, type: secret, required: true}",
    )
    prior, _, services = _deployed()
    inst, deps = _installer(**services)

    pkg = parse_bundle(required.replace("instruction: x", "instruction: y"))
    await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    assert len(deps["agent_service"].updates) == 1


async def test_redeploy_updates_a_policy_through_the_governance_service():
    prior, ids, services = _deployed()
    inst, deps = _installer(**services)

    pkg = parse_bundle(DEPLOYED.replace("amount_usd: 50", "amount_usd: 75"))
    res = await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    gov = deps["governance_service"]
    [(rule_id, fields)] = gov.updates
    assert rule_id == ids["cap"]
    assert fields["params"] == {"amount_usd": 75}
    assert "enabled" not in fields
    assert gov.created == []
    assert next(e for e in res.entities if e.key == "cap").action == InstallAction.UPDATED


async def test_a_redeploy_sets_enabled_only_when_the_file_changed_it():
    prior, ids, services = _deployed()
    inst, deps = _installer(**services)

    pkg = parse_bundle(
        DEPLOYED.replace("params: {amount_usd: 50}}", "params: {amount_usd: 50}, enabled: false}")
    )
    await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    [(_, fields)] = deps["governance_service"].updates
    assert fields["enabled"] is False


async def test_a_changed_mcp_is_left_as_is_and_says_so():
    prior, _, services = _deployed()
    inst, deps = _installer(**services)

    res = await inst.install(
        parse_bundle(DEPLOYED.replace('args: ["-y", "gh"]', 'args: ["-y", "gh@2"]')),
        {},
        prior=prior,
    )

    mcp = next(e for e in res.entities if e.key == "gh")
    assert mcp.action == InstallAction.UNCHANGED
    assert "not applied" in (mcp.detail or "")
    assert deps["mcp_server_service"].calls == []
    assert deps["mcp_instance_service"].calls == []


async def test_removed_entities_are_recorded_as_orphaned_and_kept():
    prior, ids, services = _deployed()
    inst, deps = _installer(**services)

    res = await inst.install(parse_bundle(DEPLOYED.split("channels:")[0]), {}, prior=prior)

    orphans = {e.key: e for e in res.entities if e.action == InstallAction.ORPHANED}
    assert set(orphans) == {"inbox", "daily", "cap"}
    assert orphans["daily"].id == str(ids["daily"])
    assert deps["trigger_service"].updates == []


async def test_an_entity_the_bundle_reused_is_linked_by_its_id_and_never_updated():
    prior, ids, services = _deployed(action=InstallAction.REUSED)
    inst, deps = _installer(**services)

    res = await inst.install(
        parse_bundle(DEPLOYED.replace("instruction: x", "instruction: y")), {}, prior=prior
    )

    lead = next(e for e in res.entities if e.key == "lead")
    assert (lead.action, lead.id) == (InstallAction.REUSED, str(ids["lead"]))
    assert deps["agent_service"].updates == []
    assert deps["agent_service"].calls == []


async def test_an_installed_entity_deleted_since_is_created_again():
    prior, _, services = _deployed()
    services["skill_service"] = FakeSkillSvc()
    inst, deps = _installer(**services)

    pkg = parse_bundle(DEPLOYED)
    res = await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    actions = {e.key: e.action for e in res.entities}
    assert actions["sk"] == InstallAction.CREATED
    # the agent points at the new skill id, so it is updated too
    assert actions["lead"] == InstallAction.UPDATED
    [(_, payload)] = deps["agent_service"].updates
    assert [str(i) for i in payload.skill_ids] == [
        next(e.id for e in res.entities if e.key == "sk")
    ]


async def test_dashed_keys_name_their_triggers():
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: seo\n'
        "agents: [{key: lead-agent, name: Lead, model: gpt-4o}]\n"
        "channels: [{key: tg-inbox, name: TG, agent: lead-agent}]\n"
        "automations:\n"
        '  - {key: morning-report, cron: "0 9 * * *", agent: lead-agent, prompt: go}\n'
    )
    inst, deps = _installer()
    await inst.install(pkg, {})
    assert sorted(t.name for t in deps["trigger_service"].created) == [
        "seo:morning-report",
        "seo:tg-inbox",
    ]


def _with(prior, key, **update):
    entities = [e.model_copy(update=update) if e.key == key else e for e in prior.result.entities]
    return PriorInstall(
        bundle=prior.bundle, result=prior.result.model_copy(update={"entities": entities})
    )


class _Alive:
    async def ref_exists(self, kind, entity_id):
        return True

    async def find_trigger(self, name, agent_id, recorded):
        return None

    async def find_policy(self, policy, agent_id):
        return None

    async def channel_credential_keys(self, entity_id):
        return None


async def test_a_redeploy_records_what_it_applied():
    prior, _, services = _deployed()
    inst, _ = _installer(**services)

    res = await inst.install(parse_bundle(DEPLOYED), {}, prior=prior)

    assert all(e.fingerprint for e in res.entities)


async def test_a_changed_setup_value_is_applied_and_remembered():
    model_setup = DEPLOYED.replace(
        "setup:\n", "setup:\n  - {key: model, label: Model, required: true}\n"
    ).replace("model: gpt-4o", 'model: "${setup.model}"')
    prior, ids, services = _deployed()
    prior = PriorInstall(
        bundle=parse_bundle(model_setup),
        result=prior.result.model_copy(update={"setup_values": {"model": "m1"}}),
    )
    inst, deps = _installer(**services)

    pkg = parse_bundle(model_setup)
    res = await inst.install(pkg, {"model": "m2"}, prior=prior, approved_updates=_every(pkg))

    [(agent_id, payload)] = deps["agent_service"].updates
    assert (agent_id, payload.model_id) == (ids["lead"], "m2")
    assert res.setup_values == {"model": "m2"}

    again, deps = _installer(**services)
    rerun = await again.install(
        parse_bundle(model_setup), {}, prior=PriorInstall(parse_bundle(model_setup), res)
    )
    assert len(deps["agent_service"].updates) == 1
    assert next(e for e in rerun.entities if e.key == "lead").action == InstallAction.UNCHANGED


async def test_secret_setup_values_are_not_remembered():
    prior, _, services = _deployed()
    inst, _ = _installer(**services, secret_manager=FakeSecretManager())

    pkg = parse_bundle(DEPLOYED)
    res = await inst.install(pkg, {"bot": "t0ken"}, prior=prior, approved_updates=_every(pkg))

    assert res.setup_values == {}
    assert "t0ken" not in res.model_dump_json()


async def test_an_unapplied_mcp_change_keeps_being_reported():
    prior, _, services = _deployed()
    edited = parse_bundle(DEPLOYED.replace('args: ["-y", "gh"]', 'args: ["-y", "gh@2"]'))
    inst, _ = _installer(**services)

    res = await inst.install(edited, {}, prior=prior)

    next_prior = PriorInstall(bundle=edited, result=res)
    preview = await BundleAnalyzer(existence=_Alive(), prior=next_prior).analyze(edited)
    mcp = next(e for e in preview.entities if e.key == "gh")
    assert mcp.status == EntityStatus.CHANGES_NOT_APPLIED

    again, _ = _installer(**services)
    rerun = await again.install(edited, {}, prior=next_prior)
    assert "not applied" in (next(e for e in rerun.entities if e.key == "gh").detail or "")


async def test_a_skipped_entity_keeps_its_ownership():
    prior, ids, services = _deployed()
    broken = parse_bundle(
        DEPLOYED.replace('command: npx, args: ["-y", "gh"]', 'command: "./bin/gh"')
    )
    inst, deps = _installer(**services)

    res = await inst.install(broken, {}, prior=prior, approved_updates=_every(broken))

    gh = next(e for e in res.entities if e.key == "gh")
    assert (gh.action, gh.id) == (InstallAction.SKIPPED, str(ids["gh"]))
    assert PriorInstall(bundle=broken, result=res).owned(EntityKind.MCP, "gh") is not None
    [(_, payload)] = deps["agent_service"].updates
    assert payload.tools == []


async def test_a_reused_dependency_gone_since_is_created_and_the_agent_points_at_it():
    prior, ids, services = _deployed()
    prior = _with(prior, "sk", action=InstallAction.REUSED)
    services["skill_service"] = FakeSkillSvc()
    inst, deps = _installer(**services)

    pkg = parse_bundle(DEPLOYED)
    res = await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    sk = next(e for e in res.entities if e.key == "sk")
    assert sk.action == InstallAction.CREATED
    [(agent_id, payload)] = deps["agent_service"].updates
    assert agent_id == ids["lead"]
    assert [str(i) for i in payload.skill_ids] == [sk.id]


# -- writes the authorized plan did not approve --------------------------------


async def test_an_update_the_plan_did_not_approve_is_refused():
    prior, _, services = _deployed()
    inst, deps = _installer(**services)

    with pytest.raises(BundleInstallError, match="lead"):
        await inst.install(
            parse_bundle(DEPLOYED.replace("instruction: x", "instruction: y")), {}, prior=prior
        )

    assert deps["agent_service"].updates == []


async def test_a_credential_rewrite_the_plan_did_not_approve_is_refused():
    prior, _, services = _deployed()
    sm = FakeSecretManager()
    inst, _ = _installer(**services, secret_manager=sm)

    with pytest.raises(BundleInstallError, match="inbox"):
        await inst.install(parse_bundle(DEPLOYED), {"bot": "new"}, prior=prior)

    assert sm.secrets == {}


async def test_an_update_the_caller_may_not_edit_is_refused_at_the_write():
    prior, ids, services = _deployed()
    asked = []

    async def may_edit(kind, entity_id):
        asked.append((kind, entity_id))
        return False

    services["may_edit"] = may_edit
    inst, deps = _installer(**services)
    edited = parse_bundle(DEPLOYED.replace("instruction: x", "instruction: y"))

    with pytest.raises(BundleInstallError):
        await inst.install(edited, {}, prior=prior, approved_updates=_every(edited))

    assert asked == [(EntityKind.AGENT, str(ids["lead"]))]
    assert deps["agent_service"].updates == []


async def test_a_skill_moved_to_github_is_reported_not_applied_and_writes_nothing():
    prior, _, services = _deployed()
    moved = parse_bundle(
        DEPLOYED.replace(
            '{key: sk, name: Audit, source_type: content, content: "# a"}',
            '{key: sk, name: Audit2, source_type: github, source_url: "https://github.com/x/y"}',
        )
    )
    preview = await BundleAnalyzer(existence=_Alive(), prior=prior).analyze(moved)
    approved = {(e.kind, e.key) for e in preview.entities if e.status is EntityStatus.WILL_UPDATE}
    inst, deps = _installer(**services)

    res = await inst.install(moved, {}, prior=prior, approved_updates=approved)

    assert approved == set()
    sk = next(e for e in res.entities if e.key == "sk")
    assert (sk.action, sk.detail) == (InstallAction.UNCHANGED, GITHUB_SKILL_NOT_APPLIED)
    skills = deps["skill_service"]
    assert skills.github_calls == []
    assert skills.contents == []
    assert skills.renames == []
    assert deps["agent_service"].updates == []


# -- MCPs from the catalog -------------------------------------------------------

CATALOG_MCP = """
schema_version: "0.1.0"
name: pay
setup:
  - {key: key, label: Key, type: secret, required: true}
mcps:
  - {key: pay, name: Payments, catalog: ru.yookassa/mcp, bindings: {Authorization: "Bearer ${setup.key}"}}
agents: [{key: a, name: A, model: gpt-4o, mcps: [pay]}]
"""


def _catalog_spec(**transport):
    fields = {"json_spec": {}, "remote_url": None, "cmd": None, "docker_image_url": None}
    return SimpleNamespace(id=uuid4(), **{**fields, **transport})


@pytest.mark.parametrize(
    ("transport", "target"),
    [
        ({"remote_url": "https://pay.example/mcp"}, "headers"),
        ({"cmd": ["npx", "-y", "@pay/mcp"]}, "environment"),
    ],
)
async def test_a_catalog_mcp_is_an_instance_of_the_catalog_spec_with_its_bindings(
    transport, target
):
    spec = _catalog_spec(**transport)
    servers = FakeMcpServerSvc(catalog={"ru.yookassa/mcp": spec})
    inst, deps = _installer(mcp_server_service=servers)

    res = await inst.install(parse_bundle(CATALOG_MCP), {"key": "k"})

    (created,) = deps["mcp_instance_service"].calls
    assert created.server_spec_id == spec.id
    assert created.json_spec == {target: {"Authorization": "Bearer k"}}
    assert servers.calls == []
    assert next(e for e in res.entities if e.key == "pay").action == InstallAction.CREATED
    (instance,) = deps["mcp_instance_service"].created
    assert [(t.type, t.name) for t in deps["agent_service"].calls[0].tools] == [
        ("mcp", str(instance.id))
    ]


async def test_an_unknown_catalog_mcp_is_a_validation_error_and_leaves_nothing():
    pkg = parse_bundle(
        CATALOG_MCP.replace(
            "mcps:\n",
            'mcps:\n  - {key: gh, name: GitHub, json_spec: {type: command, command: npx, args: ["-y", "gh"]}}\n',
        )
    )
    inst, deps, log = _compensating_installer()

    with pytest.raises(BundleValidationError, match=r"ru\.yookassa/mcp"):
        await inst.install(pkg, {"key": "k"})

    assert [kind for kind, _ in log.deleted] == ["instance", "spec"]
    assert deps["agent_service"].calls == []


# -- files and github skills -----------------------------------------------------

FILES_SKILL = """
schema_version: "0.1.0"
name: kit
skills:
  - key: sk
    name: Kit
    source_type: files
    files: {"SKILL.md": "# kit", "refs/notes.md": "notes"}
"""


async def test_a_files_skill_is_created_from_an_archive_of_exactly_its_files():
    inst, deps = _installer()

    res = await inst.install(parse_bundle(FILES_SKILL), {})

    [(data, name)] = deps["skill_service"].zips
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        files = {path: archive.read(path).decode() for path in archive.namelist()}
    assert files == {"SKILL.md": "# kit", "refs/notes.md": "notes"}
    assert name == "Kit"
    assert deps["skill_service"].calls == []
    assert next(e for e in res.entities if e.key == "sk").action == InstallAction.CREATED


async def test_a_changed_files_skill_is_replaced_from_its_files_on_redeploy():
    first, _ = _installer()
    pkg = parse_bundle(FILES_SKILL)
    created = await first.install(pkg, {})
    skill_id = UUID(next(e.id for e in created.entities if e.key == "sk"))

    edited = parse_bundle(FILES_SKILL.replace('"notes"', '"more notes"'))
    skills = FakeSkillSvc(known={skill_id: SimpleNamespace(id=skill_id, name="Kit")})
    inst, _ = _installer(skill_service=skills)
    res = await inst.install(
        edited,
        {},
        prior=PriorInstall(bundle=pkg, result=created),
        approved_updates={(EntityKind.SKILL, "sk")},
    )

    assert skills.packages == [(skill_id, {"SKILL.md": "# kit", "refs/notes.md": "more notes"})]
    assert skills.zips == []
    assert skills.contents == []
    assert next(e for e in res.entities if e.key == "sk").action == InstallAction.UPDATED


GITHUB_SKILL = """
schema_version: "0.1.0"
name: gh
skills:
  - {key: review, name: Review, source_type: github, source_url: "https://github.com/o/r"}
"""


async def test_a_changed_github_skill_is_not_reimported_and_keeps_its_fingerprint():
    skill_id = uuid4()
    prior = PriorInstall(
        bundle=parse_bundle(GITHUB_SKILL),
        result=InstallResult(
            bundle_name="gh",
            entities=[
                InstalledEntity(
                    kind=EntityKind.SKILL,
                    key="review",
                    name="Review",
                    action=InstallAction.CREATED,
                    id=str(skill_id),
                )
            ],
        ),
    )
    applied = prior.fingerprint(EntityKind.SKILL, "review")
    skills = FakeSkillSvc(known={skill_id: SimpleNamespace(id=skill_id, name="Review")})
    inst, _ = _installer(skill_service=skills)

    res = await inst.install(parse_bundle(GITHUB_SKILL.replace("o/r", "o/r2")), {}, prior=prior)

    (review,) = res.entities
    assert review.action == InstallAction.UNCHANGED
    assert review.detail == GITHUB_SKILL_NOT_APPLIED
    assert review.fingerprint == applied
    assert skills.github_calls == []
    assert skills.contents == []
    assert skills.packages == []


# -- compensation on a redeploy --------------------------------------------------


async def test_a_failed_redeploy_keeps_what_it_created_once_it_has_updated_in_place():
    prior, ids, services = _deployed()
    deleted = []

    class Skills(FakeSkillSvc):
        async def delete(self, skill_id):
            deleted.append(("skill", skill_id))

    class Agents(FakeAgentSvc):
        async def delete_agent(self, agent_id):
            deleted.append(("agent", agent_id))

    class Triggers(FakeTriggerSvc):
        async def update_trigger_from_payload(self, trigger_id, payload):
            raise RuntimeError("scheduler down")

        async def delete_trigger(self, trigger_id):
            deleted.append(("trigger", trigger_id))

    services["skill_service"] = Skills(known=services["skill_service"].known)
    services["agent_service"] = Agents(known=services["agent_service"].known)
    triggers = Triggers(known=services["trigger_service"].known)
    triggers.stream_service = services["trigger_service"].stream_service
    services["trigger_service"] = triggers
    inst, deps = _installer(**services)
    edited = DEPLOYED.replace(
        'skills:\n  - {key: sk, name: Audit, source_type: content, content: "# a"}',
        'skills:\n  - {key: sk, name: Audit, source_type: content, content: "# a"}\n'
        '  - {key: sk2, name: Extra, source_type: content, content: "# e"}',
    ).replace(
        "instruction: x, mcps: [gh], skills: [sk]", "instruction: y, mcps: [gh], skills: [sk, sk2]"
    )
    edited = edited.replace("prompt: go}", "prompt: go now}")

    pkg = parse_bundle(edited)
    with pytest.raises(RuntimeError, match="scheduler down"):
        await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    # The updated agent already points at the new skill, so the skill stays.
    assert deleted == []
    assert inst.updated_in_place is True
    partial = inst.partial_result()
    assert {e.key for e in partial.entities} >= {"sk", "sk2", "lead", "daily"}
    [(agent_id, payload)] = deps["agent_service"].updates
    assert agent_id == ids["lead"]
    assert payload.instruction == "y"


async def test_a_failed_install_removes_the_workspace_copy_a_catalog_mcp_made():
    copy_id = uuid4()

    class Instances(FakeMcpInstSvc):
        async def create_instance(self, payload):
            self.calls.append(payload)
            return SimpleNamespace(id=uuid4(), server_spec_id=copy_id)

    class FailingAgents(FakeAgentSvc):
        async def create_agent(self, payload):
            raise RuntimeError("database went away")

    spec = _catalog_spec(remote_url="https://pay.example/mcp")
    inst, _deps, log = _compensating_installer(agent_service=FailingAgents())
    inst._mcp_server_service.catalog = {"ru.yookassa/mcp": spec}
    instances = Instances()
    instances_deleted = log.deleted

    async def delete_instance(id):
        instances_deleted.append(("instance", id))
        return True

    instances.delete_instance = delete_instance
    inst._mcp_instance_service = instances

    with pytest.raises(RuntimeError):
        await inst.install(parse_bundle(CATALOG_MCP), {"key": "k"})

    assert [kind for kind, _ in log.deleted] == ["instance", "spec"]
    assert log.deleted[1][1] == copy_id


async def test_a_redeploy_that_leaves_enabled_alone_keeps_a_toggle_made_in_the_workspace():
    prior, ids, services = _deployed()
    inst, deps = _installer(**services)

    pkg = parse_bundle(DEPLOYED.replace("prompt: go}", "prompt: go now}"))
    await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    ts = deps["trigger_service"]
    assert [trigger_id for trigger_id, _ in ts.updates] == [ids["daily"]]
    assert ts.enabled == []
    assert ts.disabled == []


async def test_a_partial_failure_removes_only_the_entity_it_interrupted():
    inst, _ = _installer()
    deleted = []

    async def delete(what):
        deleted.append(what)

    inst._track("finished skill", lambda: delete("skill"))
    inst.result.entities.append(
        InstalledEntity(kind=EntityKind.SKILL, key="sk", name="sk", action=InstallAction.CREATED)
    )
    inst._track("channel stream", lambda: delete("stream"))
    inst._track("channel credential", lambda: delete("secret"))

    await inst._undo_created(unfinished_only=True)

    assert deleted == ["secret", "stream"]


# -- a redeploy manages only what the folder declares --------------------------


def _agent_with(services, ids, *, tools, skills=(), approvals=None):
    agent = services["agent_service"].known[str(ids["lead"])]
    agent.tools = tools
    agent.skills = [SimpleNamespace(id=i) for i in skills]
    services["agent_service"].approvals = approvals or {}


async def test_a_redeploy_keeps_the_tools_and_skills_added_in_the_workspace():
    prior, ids, services = _deployed()
    ui_skill = uuid4()
    _agent_with(
        services,
        ids,
        tools=[
            {
                "type": "mcp",
                "name": str(ids["gh"]),
                "settings": {"allowed_tools": [{"tool_name": "push"}]},
            },
            {"type": "code", "name": "agentarea/shell"},
            {"type": "agent", "name": "helper", "settings": {"agent_id": str(uuid4())}},
        ],
        skills=[ids["sk"], ui_skill],
    )
    inst, deps = _installer(**services)

    pkg = parse_bundle(
        DEPLOYED.replace("instruction: x", "instruction: y, toolsets: [agentarea/files]")
    )
    await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    [(_, payload)] = deps["agent_service"].updates
    tools = [t.model_dump(exclude_none=True) for t in payload.tools]
    assert [(t["type"], t["name"]) for t in tools] == [
        ("mcp", str(ids["gh"])),
        ("code", "agentarea/shell"),
        ("agent", "helper"),
        ("code", "agentarea/files"),
    ]
    # the settings the workspace gave a declared tool stay
    assert tools[0]["settings"]["allowed_tools"][0]["tool_name"] == "push"
    assert payload.skill_ids == [ids["sk"], ui_skill]


async def test_a_redeploy_drops_what_the_folder_no_longer_declares():
    previous = DEPLOYED.replace("instruction: x,", "instruction: x, toolsets: [agentarea/shell],")
    prior, ids, services = _deployed(text=previous)
    _agent_with(
        services,
        ids,
        tools=[
            {"type": "mcp", "name": str(ids["gh"])},
            {"type": "code", "name": "agentarea/shell"},
            {"type": "code", "name": "agentarea/web"},
        ],
        skills=[ids["sk"]],
    )
    inst, deps = _installer(**services)

    pkg = parse_bundle(DEPLOYED.replace("mcps: [gh], skills: [sk]", "mcps: [], skills: []"))
    await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    [(_, payload)] = deps["agent_service"].updates
    assert [t.name for t in payload.tools] == ["agentarea/web"]
    assert payload.skill_ids == []


async def test_a_redeploy_keeps_every_approval_the_agent_has():
    prior, ids, services = _deployed()
    _agent_with(
        services,
        ids,
        tools=[{"type": "code", "name": "agentarea/web"}],
        approvals={"agentarea/web": True, "agentarea/shell": True},
    )
    inst, deps = _installer(**services)

    pkg = parse_bundle(
        DEPLOYED.replace("instruction: x,", "instruction: y, toolsets: [agentarea/shell],")
    )
    await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    [(_, payload)] = deps["agent_service"].updates
    flags = {
        t.name: t.settings.requires_user_confirmation for t in payload.tools if t.type == "code"
    }
    assert flags == {"agentarea/web": True, "agentarea/shell": True}


async def test_an_agent_is_created_with_its_reasoning_and_client():
    client = uuid4()
    pkg = parse_bundle(
        FULL.replace(
            "model: gpt-4o,", f'model: gpt-4o, reasoning_effort: high, client: "{client}",'
        )
    )
    inst, deps = _installer()
    await inst.install(pkg, {"token": "t"})

    (created,) = deps["agent_service"].calls
    assert (created.reasoning_effort, created.reasoning_max_tokens, created.client_id) == (
        "high",
        None,
        client,
    )


async def test_a_redeploy_sets_reasoning_and_client_only_when_the_folder_names_them():
    prior, _, services = _deployed()
    inst, deps = _installer(**services)
    pkg = parse_bundle(DEPLOYED.replace("instruction: x", "instruction: y"))
    await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    [(_, untouched)] = deps["agent_service"].updates
    assert {"reasoning_effort", "reasoning_max_tokens", "client_id"}.isdisjoint(
        untouched.model_dump(exclude_unset=True)
    )

    declared = DEPLOYED.replace("model: gpt-4o,", "model: gpt-4o, reasoning_max_tokens: 2048,")
    prior, _, services = _deployed()
    inst, deps = _installer(**services)
    pkg = parse_bundle(declared)
    await inst.install(pkg, {}, prior=prior, approved_updates=_every(pkg))

    [(_, payload)] = deps["agent_service"].updates
    assert payload.model_dump(exclude_unset=True)["reasoning_effort"] is None
    assert payload.reasoning_max_tokens == 2048

    # dropped from the folder, the setting is cleared again
    prior, _, services = _deployed(text=declared)
    inst, deps = _installer(**services)
    await inst.install(
        parse_bundle(DEPLOYED), {}, prior=prior, approved_updates=_every(parse_bundle(DEPLOYED))
    )
    [(_, cleared)] = deps["agent_service"].updates
    assert cleared.model_dump(exclude_unset=True)["reasoning_max_tokens"] is None


async def test_a_credential_that_names_a_secret_is_never_replaced_by_a_value():
    prior, ids, services = _deployed()
    stored = '{"bot_token": {"secret_name": "tg-bot"}}'
    sm = FakeSecretManager({ids["credentials"]: stored})
    inst, _ = _installer(**services, secret_manager=sm)

    pkg = parse_bundle(DEPLOYED)
    with pytest.raises(BundleValidationError, match="bot_token name a workspace secret"):
        await inst.install(pkg, {"bot": "literal"}, prior=prior, approved_updates=_every(pkg))

    assert sm.secrets == {ids["credentials"]: stored}
