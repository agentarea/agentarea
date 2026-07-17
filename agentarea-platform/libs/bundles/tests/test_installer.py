"""Installer orchestration tests (mocked domain services)."""

from types import SimpleNamespace
from uuid import uuid4

import pytest
from agentarea_bundles.application.analyzer import parse_bundle
from agentarea_bundles.application.installer import BundleInstaller, BundleInstallError
from agentarea_bundles.schemas.result import InstallAction

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


class FakeMcpServerSvc:
    def __init__(self): self.calls = []
    async def create_mcp_server(self, payload):
        self.calls.append(payload)
        return SimpleNamespace(id=uuid4())


class FakeMcpInstSvc:
    def __init__(self, existing=None): self.existing = existing; self.calls = []
    async def get_by_name(self, name): return self.existing
    async def create_instance(self, payload):
        self.calls.append(payload)
        return SimpleNamespace(id=uuid4())


class FakeSkillSvc:
    def __init__(self): self.calls = []
    async def create_from_content(self, payload):
        self.calls.append(payload)
        return SimpleNamespace(id=uuid4())


class FakeSkillRepo:
    def __init__(self, existing=None): self.existing = existing
    async def get_by_name(self, name): return self.existing


class FakeAgentSvc:
    def __init__(self): self.calls = []
    async def create_agent(self, payload):
        self.calls.append(payload)
        return SimpleNamespace(id=uuid4())


class FakeAgentRepo:
    def __init__(self, existing=None): self.existing = existing
    async def get_agent_by_name(self, name): return self.existing


class FakeTriggerSvc:
    def __init__(self): self.created = []; self.disabled = []
    async def create_trigger(self, domain):
        t = SimpleNamespace(id=uuid4(), name=domain.name)
        self.created.append(domain)
        return t
    async def disable_trigger(self, trigger_id):
        self.disabled.append(trigger_id)
        return True


class FakeTriggerRepo:
    def __init__(self, existing=None): self.existing = existing or []
    async def list_all(self): return self.existing


class FakeGovernanceSvc:
    def __init__(self, existing=None): self.existing = existing or []; self.created = []
    async def list_rules(self, **kwargs): return self.existing
    async def create_rule(self, *, rule, subject_id):
        self.created.append((rule, subject_id))
        return SimpleNamespace(id=uuid4())


def _installer(**overrides):
    deps = dict(
        mcp_server_service=FakeMcpServerSvc(),
        mcp_instance_service=FakeMcpInstSvc(),
        skill_service=FakeSkillSvc(),
        skill_repository=FakeSkillRepo(),
        agent_service=FakeAgentSvc(),
        agent_repository=FakeAgentRepo(),
        trigger_service=FakeTriggerSvc(),
        trigger_repository=FakeTriggerRepo(),
        governance_service=FakeGovernanceSvc(),
        user_context=SimpleNamespace(user_id="u", workspace_id="w"),
    )
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


async def test_policies_install_on_workspace_and_agent():
    inst, deps = _installer()
    res = await inst.install(parse_bundle(POLICIES), {})
    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("policy", "cap")] == InstallAction.CREATED
    assert actions[("policy", "deny")] == InstallAction.CREATED
    gov = deps["governance_service"]
    assert len(gov.created) == 2
    # workspace cap bound to workspace id; agent deny bound to the created agent id
    subjects = {str(r.subject_type): sid for r, sid in gov.created}
    assert subjects["workspace"] == "w"
    # message folded into params
    deny_rule = next(r for r, _ in gov.created if r.effect.value == "deny")
    assert deny_rule.params.get("message") == "no email"


async def test_policy_idempotent_when_rule_exists():
    inst, deps = _installer(governance_service=FakeGovernanceSvc(existing=[SimpleNamespace(id=uuid4())]))
    res = await inst.install(parse_bundle(POLICIES), {})
    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("policy", "cap")] == InstallAction.REUSED
    assert deps["governance_service"].created == []  # nothing created


async def test_policy_skipped_when_agent_subject_missing():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: p
policies: [{key: orphan, subject: ghost, target: "*", effect: deny}]
"""
    )
    inst, deps = _installer()
    res = await inst.install(pkg, {})
    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("policy", "orphan")] == InstallAction.SKIPPED
    assert deps["governance_service"].created == []


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
    # agent wired to mcp by instance name + skill id
    agent = deps["agent_service"].calls[0]
    assert [(t.type, t.name) for t in agent.tools] == [("mcp", "GitHub")]
    assert len(agent.skill_ids) == 1


async def test_disabled_automation_is_disabled_after_create():
    inst, deps = _installer()
    await inst.install(parse_bundle(FULL), {"token": "secret"})
    ts = deps["trigger_service"]
    assert len(ts.created) == 1
    assert len(ts.disabled) == 1  # disable_trigger called for enabled=false


async def test_enabled_automation_not_disabled():
    pkg = parse_bundle(FULL.replace("enabled: false", "enabled: true"))
    inst, deps = _installer()
    await inst.install(pkg, {"token": "secret"})
    assert deps["trigger_service"].disabled == []


class FakeSecretManager:
    def __init__(self):
        self.secrets: dict[str, str] = {}

    async def set_secret(self, name, value):
        self.secrets[name] = value


CHANNEL = """
schema_version: "0.1.0"
name: tg
setup:
  - {key: bot, label: Bot Token, type: secret, required: true}
agents: [{key: lead, name: Lead, model: gpt-4o}]
channels:
  - {key: inbox, type: telegram, name: TG Inbox, agent: lead, bindings: {bot_token: "${setup.bot}"}, enabled: false}
"""


async def test_channel_installs_telegram_trigger_and_stores_secret():
    sm = FakeSecretManager()
    inst, deps = _installer(secret_manager=sm)
    res = await inst.install(parse_bundle(CHANNEL), {"bot": "12345:secret"})

    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("channel", "inbox")] == InstallAction.CREATED

    # a trigger was created for the agent and imported disabled
    ts = deps["trigger_service"]
    assert len(ts.created) == 1
    assert ts.created[0].name == "tg:inbox"
    assert len(ts.disabled) == 1

    # the resolved bot token is stored under the exact key the outbound delivery
    # adapter reads: channel_cred:{type}:{trigger_id}
    assert len(sm.secrets) == 1
    name, blob = next(iter(sm.secrets.items()))
    assert name.startswith("channel_cred:telegram:")
    assert "12345:secret" in blob


async def test_channel_created_without_secret_manager():
    # No secret manager → trigger still provisioned; credential just isn't stored.
    inst, deps = _installer(secret_manager=None)
    res = await inst.install(parse_bundle(CHANNEL), {"bot": "x"})
    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("channel", "inbox")] == InstallAction.CREATED
    assert len(deps["trigger_service"].created) == 1


async def test_channel_skipped_when_agent_missing():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: tg
channels:
  - {key: inbox, type: telegram, name: TG, agent: ghost, bindings: {}, enabled: false}
"""
    )
    inst, deps = _installer()
    res = await inst.install(pkg, {})
    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("channel", "inbox")] == InstallAction.SKIPPED
    assert deps["trigger_service"].created == []


async def test_idempotent_reuse_of_existing_entities():
    existing_skill = SimpleNamespace(id=uuid4())
    existing_agent = SimpleNamespace(id=uuid4())
    existing_inst = SimpleNamespace(id=uuid4())
    inst, deps = _installer(
        skill_repository=FakeSkillRepo(existing=existing_skill),
        agent_repository=FakeAgentRepo(existing=existing_agent),
        mcp_instance_service=FakeMcpInstSvc(existing=existing_inst),
        trigger_repository=FakeTriggerRepo(existing=[SimpleNamespace(name="seo:daily")]),
    )
    res = await inst.install(parse_bundle(FULL), {"token": "secret"})
    actions = {(e.kind, e.key): e.action for e in res.entities}
    assert actions[("mcp", "gh")] == InstallAction.REUSED
    assert actions[("skill", "sk")] == InstallAction.REUSED
    assert actions[("agent", "lead")] == InstallAction.REUSED
    assert actions[("automation", "daily")] == InstallAction.REUSED
    # nothing newly created
    assert deps["agent_service"].calls == []
    assert deps["skill_service"].calls == []


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
    assert deps["agent_service"].calls[0].tools is None
