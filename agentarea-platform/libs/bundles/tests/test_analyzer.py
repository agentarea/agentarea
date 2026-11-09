"""Analyzer / import-preview tests."""

from uuid import UUID

import pytest
from agentarea_bundles.application.analyzer import (
    BundleAnalyzer,
    BundleParseError,
    CatalogMcp,
    PriorInstall,
    parse_bundle,
    skill_content_error,
)
from agentarea_bundles.schemas.preview import EntityKind, EntityStatus, IssueSeverity
from agentarea_bundles.schemas.result import InstallAction, InstalledEntity, InstallResult

GOOD = """
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
  - {key: daily, type: cron, cron: "0 9 * * *", agent: lead, prompt: go}
"""


async def test_parse_invalid_yaml():
    with pytest.raises(BundleParseError):
        parse_bundle(":\n  - [")


async def test_parse_empty():
    with pytest.raises(BundleParseError):
        parse_bundle("   ")


async def test_good_bundle_is_installable():
    preview = await BundleAnalyzer().analyze(parse_bundle(GOOD))
    assert preview.installable is True
    assert not preview.block_issues
    kinds = {(e.kind, e.key): e.status for e in preview.entities}
    assert all(s == EntityStatus.WILL_CREATE for s in kinds.values())


async def test_unknown_mcp_ref_blocks():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: p
agents: [{key: a, name: A, model: gpt-4o, mcps: [missing]}]
"""
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False
    assert any("unknown mcp 'missing'" in i.message for i in preview.block_issues)


async def test_binding_unknown_setup_field_blocks():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: p
mcps:
  - key: gh
    name: GitHub
    json_spec: {type: command, command: npx}
    bindings: {GH_TOKEN: "${setup.nope}"}
agents: [{key: a, name: A, model: gpt-4o}]
"""
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False
    assert any("unknown setup field 'nope'" in i.message for i in preview.block_issues)


async def test_unsupported_mcp_warns_not_blocks():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: p
mcps:
  - {key: bad, name: Bad, json_spec: {type: command, command: "./local/bin"}}
agents: [{key: a, name: A, model: gpt-4o, mcps: [bad]}]
"""
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is True  # warning, not block
    statuses = {e.key: e.status for e in preview.entities}
    assert statuses["bad"] == EntityStatus.UNSUPPORTED
    assert any(i.severity == IssueSeverity.WARN for i in preview.issues)


async def test_agent_without_model_blocks():
    pkg = parse_bundle('schema_version: "0.1.0"\nname: p\nagents: [{key: a, name: A}]\n')
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False
    assert any("has no model" in i.message for i in preview.block_issues)


class _AllExist:
    async def ref_exists(self, kind, entity_id):
        return True

    async def find_trigger(self, name, agent_id, recorded):
        return "x"

    async def find_policy(self, policy, agent_id):
        return None

    async def channel_credential_keys(self, entity_id):
        return None


async def test_without_a_record_of_an_earlier_install_nothing_already_exists():
    preview = await BundleAnalyzer(existence=_AllExist()).analyze(parse_bundle(GOOD))
    statuses = {(e.kind, e.key): e.status for e in preview.entities}
    assert statuses[("skill", "sk")] == EntityStatus.WILL_CREATE
    assert statuses[("agent", "lead")] == EntityStatus.WILL_CREATE
    # its agent is new, so no trigger can be the bundle's yet
    assert statuses[("automation", "daily")] == EntityStatus.WILL_CREATE


async def test_policy_preview_entities():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: p
agents: [{key: lead, name: Lead, model: gpt-4o}]
policies:
  - {key: cap, subject: workspace, target: spend, effect: cap, params: {amount_usd: 50}}
  - {key: deny, subject: lead, target: "tool:send_email", effect: deny}
"""
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is True
    pol = {e.key: e for e in preview.entities if e.kind.value == "policy"}
    assert set(pol) == {"cap", "deny"}
    assert "cap spend on workspace" in pol["cap"].detail


async def test_policy_unknown_subject_blocks():
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: p\n'
        'policies: [{key: x, subject: ghost, target: "*", effect: deny}]\n'
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False
    assert any("subject 'ghost'" in i.message for i in preview.block_issues)


async def test_policy_invalid_target_blocks():
    # A target the governance compiler can't parse would install but never
    # enforce; analyze must block it instead of shipping a silent no-op deny.
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: p\n'
        'policies: [{key: x, subject: workspace, target: "bogus:thing", effect: deny}]\n'
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False
    assert any("target 'bogus:thing' is invalid" in i.message for i in preview.block_issues)


async def test_policy_unenforceable_params_block():
    # The target parses, so the old target-only check passed it — but the
    # compiler reads `period` as month|run and skips anything else, so this
    # installs a cap that never fires.
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: p\npolicies:\n'
        "  - {key: x, subject: workspace, target: spend, effect: cap, "
        "params: {amount_usd: 10, period: day}}\n"
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False
    assert any("period" in i.message for i in preview.block_issues)


async def test_policy_wildcard_deny_blocks():
    # deny/allow compile to a named tool; a wildcard one is dropped by the
    # compiler, so a bundle promising "denies everything" enforces nothing.
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: p\n'
        'policies: [{key: x, subject: workspace, target: "tool:*", effect: deny}]\n'
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False


async def test_duplicate_policy_key_blocks():
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: p\npolicies:\n'
        "  - {key: dup, subject: workspace, target: spend, effect: cap}\n"
        "  - {key: dup, subject: workspace, target: tokens, effect: cap}\n"
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False
    assert any("duplicate policy key 'dup'" in i.message for i in preview.block_issues)


# -- redeploy plan: diff against the previous install -------------------------

DEPLOYED = """
schema_version: "0.1.0"
name: seo
mcps:
  - {key: gh, name: GitHub, json_spec: {type: command, command: npx, args: ["-y", "gh"]}}
skills:
  - {key: sk, name: Audit, source_type: content, content: "# a"}
agents:
  - {key: lead, name: Lead, model: gpt-4o, instruction: x, mcps: [gh], skills: [sk]}
automations:
  - {key: daily, type: cron, cron: "0 9 * * *", agent: lead, prompt: go}
policies:
  - {key: cap, subject: workspace, target: spend, effect: cap, params: {amount_usd: 50}}
"""


def _prior(text=DEPLOYED, action=InstallAction.CREATED):
    bundle = parse_bundle(text)
    entities = []
    for kind, items in (
        (EntityKind.MCP, bundle.mcps),
        (EntityKind.SKILL, bundle.skills),
        (EntityKind.AGENT, bundle.agents),
        (EntityKind.CHANNEL, bundle.channels),
        (EntityKind.AUTOMATION, bundle.automations),
        (EntityKind.POLICY, bundle.policies),
    ):
        for item in items:
            entities.append(
                InstalledEntity(
                    kind=kind,
                    key=item.key,
                    name=getattr(item, "name", item.key),
                    action=action,
                    id=f"id-{item.key}",
                )
            )
    return PriorInstall(
        bundle=bundle, result=InstallResult(bundle_name=bundle.name, entities=entities)
    )


class _Refs:
    """Every previously installed id still resolves; nothing else exists by name."""

    def __init__(self, gone=(), no_credentials=(), triggers=(), rules=None, referenced=()):
        self.gone = set(gone)
        self.no_credentials = set(no_credentials)
        # channels whose stored bot_token names a workspace secret
        self.referenced = set(referenced)
        # (name, agent id, trigger id) of the workspace's triggers
        self.triggers = list(triggers)
        # {(policy key, subject agent id or None) -> rule id}
        self.rules = rules or {}

    async def ref_exists(self, kind, entity_id):
        return entity_id not in self.gone

    async def channel_credential_keys(self, entity_id):
        if entity_id in self.no_credentials:
            return {}
        return {"bot_token": entity_id in self.referenced}

    async def find_trigger(self, name, agent_id, recorded):
        return next(
            (
                t
                for n, a, t in self.triggers
                if n == name and a == agent_id and recorded in (None, t)
            ),
            None,
        )

    async def find_policy(self, policy, agent_id):
        return self.rules.get((policy.key, agent_id))


def _statuses(preview):
    return {(e.kind.value, e.key): e.status for e in preview.entities}


async def test_redeploy_of_the_same_bundle_is_unchanged():
    preview = await BundleAnalyzer(existence=_Refs(), prior=_prior()).analyze(
        parse_bundle(DEPLOYED)
    )
    assert set(_statuses(preview).values()) == {EntityStatus.UNCHANGED}
    assert preview.installable is True


async def test_edited_entities_will_update():
    edited = (
        DEPLOYED.replace("instruction: x", "instruction: y")
        .replace("prompt: go", "prompt: go now")
        .replace('content: "# a"', 'content: "# b"')
        .replace("amount_usd: 50", "amount_usd: 60")
    )
    preview = await BundleAnalyzer(existence=_Refs(), prior=_prior()).analyze(parse_bundle(edited))
    s = _statuses(preview)
    assert s[("agent", "lead")] == EntityStatus.WILL_UPDATE
    assert s[("skill", "sk")] == EntityStatus.WILL_UPDATE
    assert s[("automation", "daily")] == EntityStatus.WILL_UPDATE
    assert s[("policy", "cap")] == EntityStatus.WILL_UPDATE
    assert s[("mcp", "gh")] == EntityStatus.UNCHANGED


async def test_new_key_will_create_and_dependent_agent_will_update():
    added = DEPLOYED.replace(
        "skills:\n", 'skills:\n  - {key: sk2, name: Extra, source_type: content, content: "# e"}\n'
    ).replace("skills: [sk]", "skills: [sk, sk2]")
    preview = await BundleAnalyzer(existence=_Refs(), prior=_prior()).analyze(parse_bundle(added))
    s = _statuses(preview)
    assert s[("skill", "sk2")] == EntityStatus.WILL_CREATE
    assert s[("agent", "lead")] == EntityStatus.WILL_UPDATE


async def test_removed_keys_are_orphaned_not_deleted():
    trimmed = DEPLOYED.split("automations:")[0]
    preview = await BundleAnalyzer(existence=_Refs(), prior=_prior()).analyze(parse_bundle(trimmed))
    s = _statuses(preview)
    assert s[("automation", "daily")] == EntityStatus.ORPHANED
    assert s[("policy", "cap")] == EntityStatus.ORPHANED
    orphan = next(e for e in preview.entities if e.key == "daily")
    assert "not deleted" in (orphan.detail or "")


async def test_a_removed_entity_that_no_longer_exists_is_not_reported():
    trimmed = DEPLOYED.split("automations:")[0]
    preview = await BundleAnalyzer(
        existence=_Refs(gone={"id-daily", "id-cap"}), prior=_prior()
    ).analyze(parse_bundle(trimmed))
    assert ("automation", "daily") not in _statuses(preview)


async def test_an_installed_entity_deleted_since_is_created_again():
    preview = await BundleAnalyzer(existence=_Refs(gone={"id-sk"}), prior=_prior()).analyze(
        parse_bundle(DEPLOYED)
    )
    s = _statuses(preview)
    assert s[("skill", "sk")] == EntityStatus.WILL_CREATE
    assert s[("agent", "lead")] == EntityStatus.WILL_UPDATE


async def test_entities_the_last_install_reused_stay_already_exists():
    # The previous install linked an entity it did not create; that one is not
    # this bundle's to update, so it is linked again by its recorded id.
    prior = _prior(action=InstallAction.REUSED)
    edited = DEPLOYED.replace("instruction: x", "instruction: y")
    preview = await BundleAnalyzer(existence=_Refs(), prior=prior).analyze(parse_bundle(edited))
    s = _statuses(preview)
    assert s[("agent", "lead")] == EntityStatus.ALREADY_EXISTS
    assert s[("skill", "sk")] == EntityStatus.ALREADY_EXISTS
    assert EntityStatus.ORPHANED not in s.values()


async def test_a_reused_entity_gone_since_will_be_created():
    prior = _prior(action=InstallAction.REUSED)
    preview = await BundleAnalyzer(existence=_Refs(gone={"id-sk"}), prior=prior).analyze(
        parse_bundle(DEPLOYED)
    )
    assert _statuses(preview)[("skill", "sk")] == EntityStatus.WILL_CREATE


async def test_changed_mcp_reports_changes_not_applied():
    edited = DEPLOYED.replace('args: ["-y", "gh"]', 'args: ["-y", "gh@2"]')
    preview = await BundleAnalyzer(existence=_Refs(), prior=_prior()).analyze(parse_bundle(edited))
    mcp = next(e for e in preview.entities if e.key == "gh")
    assert mcp.status == EntityStatus.CHANGES_NOT_APPLIED
    assert "not applied" in (mcp.detail or "")
    assert any(i.severity is IssueSeverity.WARN and i.entity_key == "gh" for i in preview.issues)
    assert preview.installable is True


async def test_prior_install_is_read_from_the_stored_record():
    bundle = parse_bundle(DEPLOYED)
    result = InstallResult(
        bundle_name="seo",
        entities=[
            InstalledEntity(
                kind=EntityKind.AGENT, key="lead", name="Lead", action=InstallAction.CREATED, id="a"
            )
        ],
    )
    prior = PriorInstall.from_record(bundle.model_dump(mode="json"), result.model_dump(mode="json"))
    assert prior.owned(EntityKind.AGENT, "lead") is not None
    assert prior.owned(EntityKind.SKILL, "sk") is None


async def test_a_trigger_is_the_bundles_only_with_its_name_its_agent_and_the_recorded_id():
    pkg = parse_bundle(DEPLOYED + "channels:\n  - {key: inbox, name: Inbox, agent: lead}\n")
    prior = PriorInstall(
        bundle=pkg,
        result=InstallResult(
            bundle_name="seo",
            entities=[
                InstalledEntity(
                    kind=EntityKind.AGENT,
                    key="lead",
                    name="Lead",
                    action=InstallAction.REUSED,
                    id="id-lead",
                ),
                InstalledEntity(
                    kind=EntityKind.CHANNEL,
                    key="inbox",
                    name="seo:inbox",
                    action=InstallAction.REUSED,
                    id="id-inbox",
                ),
            ],
        ),
    )

    async def statuses(*triggers):
        preview = await BundleAnalyzer(existence=_Refs(triggers=triggers), prior=prior).analyze(pkg)
        s = _statuses(preview)
        return s[("automation", "daily")], s[("channel", "inbox")]

    ours = await statuses(("seo:daily", "id-lead", "t1"), ("seo:inbox", "id-lead", "id-inbox"))
    assert ours == (EntityStatus.ALREADY_EXISTS, EntityStatus.ALREADY_EXISTS)
    squatted = await statuses(("seo:daily", "id-other", "t1"), ("seo:inbox", "id-lead", "t2"))
    assert squatted == (EntityStatus.WILL_CREATE, EntityStatus.WILL_CREATE)
    elsewhere = await statuses(("other:daily", "id-lead", "t1"))
    assert elsewhere[0] == EntityStatus.WILL_CREATE


MODEL_SETUP = """
schema_version: "0.1.0"
name: seo
setup:
  - {key: model, label: Model, required: true}
agents:
  - {key: lead, name: Lead, model: "${setup.model}", instruction: x}
"""


def _prior_with_values(text, values):
    prior = _prior(text)
    return PriorInstall(
        bundle=prior.bundle,
        result=prior.result.model_copy(update={"setup_values": values}),
    )


async def test_a_changed_setup_value_will_update_what_uses_it():
    prior = _prior_with_values(MODEL_SETUP, {"model": "m1"})
    pkg = parse_bundle(MODEL_SETUP)

    async def status(values):
        preview = await BundleAnalyzer(existence=_Refs(), prior=prior, setup_values=values).analyze(
            pkg
        )
        return _statuses(preview)[("agent", "lead")]

    assert await status({"model": "m2"}) == EntityStatus.WILL_UPDATE
    assert await status({"model": "m1"}) == EntityStatus.UNCHANGED
    assert await status({}) == EntityStatus.UNCHANGED


async def test_a_reused_dependency_gone_since_is_created_and_updates_the_agent():
    prior = _prior()
    prior.result.entities[1] = prior.result.entities[1].model_copy(
        update={"action": InstallAction.REUSED, "id": "id-old-skill"}
    )
    preview = await BundleAnalyzer(existence=_Refs(gone={"id-old-skill"}), prior=prior).analyze(
        parse_bundle(DEPLOYED)
    )
    s = _statuses(preview)
    assert s[("skill", "sk")] == EntityStatus.WILL_CREATE
    assert s[("agent", "lead")] == EntityStatus.WILL_UPDATE


async def test_the_same_reused_dependency_leaves_the_agent_unchanged():
    prior = _prior()
    prior.result.entities[1] = prior.result.entities[1].model_copy(
        update={"action": InstallAction.REUSED, "id": "id-same"}
    )
    preview = await BundleAnalyzer(existence=_Refs(), prior=prior).analyze(parse_bundle(DEPLOYED))
    assert _statuses(preview)[("agent", "lead")] == EntityStatus.UNCHANGED


async def test_a_skipped_entity_with_a_carried_id_is_still_owned():
    prior = _prior()
    prior.result.entities[0] = prior.result.entities[0].model_copy(
        update={"action": InstallAction.SKIPPED}
    )
    assert prior.owned(EntityKind.MCP, "gh") is not None
    preview = await BundleAnalyzer(existence=_Refs(), prior=prior).analyze(parse_bundle(DEPLOYED))
    assert _statuses(preview)[("mcp", "gh")] == EntityStatus.UNCHANGED


CHANNELED = (
    DEPLOYED.replace(
        "mcps:\n", "setup:\n  - {key: bot, label: Bot, type: secret, required: true}\nmcps:\n"
    )
    + 'channels:\n  - {key: inbox, name: Inbox, agent: lead, bindings: {bot_token: "${setup.bot}"}}\n'
)


def _required(preview):
    return {f.key: f.required for f in preview.setup}


async def test_a_supplied_channel_secret_will_update_the_channel():
    prior = _prior(CHANNELED)
    pkg = parse_bundle(CHANNELED)

    plain = await BundleAnalyzer(existence=_Refs(), prior=prior).analyze(pkg)
    supplied = await BundleAnalyzer(
        existence=_Refs(), prior=prior, setup_values={"bot": "t"}
    ).analyze(pkg)

    assert _statuses(plain)[("channel", "inbox")] == EntityStatus.UNCHANGED
    assert _statuses(supplied)[("channel", "inbox")] == EntityStatus.WILL_UPDATE


async def test_a_redeploy_requires_only_the_setup_it_will_write():
    edited = parse_bundle(CHANNELED.replace("instruction: x", "instruction: y"))
    preview = await BundleAnalyzer(existence=_Refs(), prior=_prior(CHANNELED)).analyze(edited)
    assert _required(preview) == {"bot": False}

    fresh = await BundleAnalyzer(
        existence=_Refs(gone={"id-inbox"}), prior=_prior(CHANNELED)
    ).analyze(edited)
    assert _statuses(fresh)[("channel", "inbox")] == EntityStatus.WILL_CREATE
    assert _required(fresh) == {"bot": True}


async def test_a_first_install_requires_every_required_field():
    preview = await BundleAnalyzer().analyze(parse_bundle(CHANNELED))
    assert _required(preview) == {"bot": True}


class _Checks:
    def __init__(
        self,
        bad_models=(),
        bad_toolsets=(),
        bad_crons=(),
        denied=(),
        catalog=None,
        bad_clients=(),
        secret_problems=None,
    ):
        self.secret_problems = secret_problems or {}
        self.secrets_asked = []
        self.bad_models = set(bad_models)
        self.bad_clients = set(bad_clients)
        self.bad_toolsets = set(bad_toolsets)
        self.bad_crons = set(bad_crons)
        self.denied = set(denied)
        self.catalog = catalog or {}
        self.asked = []

    async def catalog_mcp(self, catalog_id):
        transport = self.catalog.get(catalog_id)
        return CatalogMcp(spec_id=f"spec-{catalog_id}", transport=transport) if transport else None

    async def agent_problem(self, agent, model_id, client_id):
        toolsets = agent.toolsets
        self.asked.append(model_id)
        if client_id in self.bad_clients:
            return f"bad client {client_id}"
        unknown = [t for t in toolsets if t in self.bad_toolsets]
        if unknown:
            return f"unknown toolset {unknown[0]}"
        return f"bad model {model_id}" if model_id in self.bad_models else None

    async def automation_problem(self, package, automation):
        return f"bad cron {automation.cron}" if automation.cron in self.bad_crons else None

    async def may_edit(self, kind, entity_id):
        return entity_id not in self.denied

    async def secret_problem(self, secret_name):
        self.secrets_asked.append(secret_name)
        return self.secret_problems.get(secret_name)


def _blocks(preview):
    return {(i.entity_key, i.message) for i in preview.block_issues}


async def test_a_model_the_workspace_cannot_resolve_blocks_before_install():
    preview = await BundleAnalyzer(checks=_Checks(bad_models={"gpt-4o"})).analyze(
        parse_bundle(GOOD)
    )
    assert preview.installable is False
    assert any(k == "lead" and "bad model gpt-4o" in m for k, m in _blocks(preview))


async def test_an_unknown_toolset_blocks_before_install():
    pkg = parse_bundle(GOOD.replace("model: gpt-4o,", "model: gpt-4o, toolsets: [nope/x],"))
    preview = await BundleAnalyzer(checks=_Checks(bad_toolsets={"nope/x"})).analyze(pkg)
    assert any(k == "lead" and "nope/x" in m for k, m in _blocks(preview))


async def test_a_bad_cron_blocks_before_install():
    preview = await BundleAnalyzer(checks=_Checks(bad_crons={"0 9 * * *"})).analyze(
        parse_bundle(GOOD)
    )
    assert any(k == "daily" and "bad cron" in m for k, m in _blocks(preview))


async def test_an_unchanged_agent_is_not_revalidated():
    checks = _Checks(bad_models={"gpt-4o"})
    preview = await BundleAnalyzer(existence=_Refs(), prior=_prior(), checks=checks).analyze(
        parse_bundle(DEPLOYED)
    )
    assert preview.installable is True
    assert checks.asked == []


async def test_an_unresolved_model_is_left_to_the_setup_check():
    checks = _Checks()
    await BundleAnalyzer(checks=checks).analyze(parse_bundle(MODEL_SETUP))
    assert checks.asked == []


async def test_an_update_the_caller_may_not_edit_blocks_per_entity():
    edited = (
        DEPLOYED.replace("instruction: x", "instruction: y")
        .replace("prompt: go", "prompt: go now")
        .replace('content: "# a"', 'content: "# b"')
    )
    checks = _Checks(denied={"id-lead", "id-daily", "id-sk"})
    preview = await BundleAnalyzer(existence=_Refs(), prior=_prior(), checks=checks).analyze(
        parse_bundle(edited)
    )
    denied = {k for k, m in _blocks(preview) if "edit" in m}
    assert denied == {"lead", "daily", "sk"}
    assert preview.installable is False


async def test_an_unchanged_entity_needs_no_edit_permission():
    checks = _Checks(denied={"id-lead", "id-daily", "id-sk", "id-cap", "id-gh"})
    preview = await BundleAnalyzer(existence=_Refs(), prior=_prior(), checks=checks).analyze(
        parse_bundle(DEPLOYED)
    )
    assert preview.installable is True


async def test_a_remembered_value_is_not_asked_again():
    prior = _prior_with_values(MODEL_SETUP, {"model": "m1"})
    edited = parse_bundle(MODEL_SETUP.replace("instruction: x", "instruction: y"))
    preview = await BundleAnalyzer(existence=_Refs(), prior=prior).analyze(edited)
    assert _statuses(preview)[("agent", "lead")] == EntityStatus.WILL_UPDATE
    assert _required(preview) == {"model": False}


async def test_a_model_left_unresolved_by_an_optional_field_blocks():
    optional = parse_bundle(MODEL_SETUP.replace("required: true", "required: false"))

    unset = await BundleAnalyzer(checks=_Checks()).analyze(optional)
    given = await BundleAnalyzer(checks=_Checks(), setup_values={"model": "m"}).analyze(optional)

    assert any(k == "lead" and "model" in m for k, m in _blocks(unset))
    assert given.installable is True


async def test_a_model_left_unresolved_by_a_required_field_is_the_setup_checks_to_report():
    preview = await BundleAnalyzer(checks=_Checks()).analyze(parse_bundle(MODEL_SETUP))
    assert preview.installable is True


GITHUB_SKILL = DEPLOYED.replace(
    '{key: sk, name: Audit, source_type: content, content: "# a"}',
    '{key: sk, name: Audit, source_type: github, source_url: "https://github.com/x/y"}',
)


async def test_a_changed_github_skill_is_reported_not_reimported():
    prior = _prior(GITHUB_SKILL)
    changed = GITHUB_SKILL.replace("github.com/x/y", "github.com/x/z")
    checks = _Checks(denied={"id-lead"})
    preview = await BundleAnalyzer(existence=_Refs(), prior=prior, checks=checks).analyze(
        parse_bundle(changed)
    )
    s = _statuses(preview)
    assert s[("skill", "sk")] == EntityStatus.CHANGES_NOT_APPLIED
    assert s[("agent", "lead")] == EntityStatus.UNCHANGED
    assert preview.installable is True
    assert any(i.severity is IssueSeverity.WARN and i.entity_key == "sk" for i in preview.issues)


async def test_a_rule_the_install_would_reuse_is_planned_as_already_existing():
    pkg = parse_bundle(
        DEPLOYED + '  - {key: deny, subject: lead, target: "tool:send_email", effect: deny}\n'
    )
    rules = {("cap", None): "rule-cap", ("deny", "id-lead"): "rule-deny"}

    first = await BundleAnalyzer(existence=_Refs(rules=rules)).analyze(pkg)
    # the workspace rule exists; the agent one cannot, its agent is new
    assert _statuses(first)[("policy", "cap")] == EntityStatus.ALREADY_EXISTS
    assert _statuses(first)[("policy", "deny")] == EntityStatus.WILL_CREATE

    prior = _prior(DEPLOYED.split("policies:")[0])
    again = await BundleAnalyzer(existence=_Refs(rules=rules), prior=prior).analyze(pkg)
    assert _statuses(again)[("policy", "deny")] == EntityStatus.ALREADY_EXISTS


async def test_a_channel_without_stored_credentials_will_update_and_needs_its_secret():
    analyzer = BundleAnalyzer(existence=_Refs(no_credentials={"id-inbox"}), prior=_prior(CHANNELED))
    preview = await analyzer.analyze(parse_bundle(CHANNELED))
    assert _statuses(preview)[("channel", "inbox")] == EntityStatus.WILL_UPDATE
    assert _required(preview) == {"bot": True}


@pytest.mark.parametrize(
    "entity",
    [
        "skills: [{key: s, name: NAME, content: hi}]",
        "agents: [{key: a, name: NAME, model: gpt-4o}]",
        "mcps: [{key: m, name: NAME, json_spec: {type: url, endpoint_url: 'https://x.test/mcp'}}]",
    ],
    ids=["skill", "agent", "mcp"],
)
async def test_an_entity_name_longer_than_its_column_is_refused_at_analyze(entity):
    # The name lands in a String(255) column; past that, install used to fail
    # halfway through, after earlier entities had committed.
    source = 'schema_version: "0.1.0"\nname: p\n' + entity + "\n"
    parse_bundle(source.replace("NAME", "n" * 255))
    with pytest.raises(BundleParseError, match="255"):
        parse_bundle(source.replace("NAME", "n" * 256))


async def test_an_automation_whose_trigger_name_is_too_long_blocks():
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: ' + "p" * 250 + "\n"
        "agents: [{key: lead, name: Lead, model: gpt-4o}]\n"
        "automations:\n"
        "  - {key: nightly_run, cron: '0 0 * * *', agent: lead, prompt: go}\n"
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False
    assert any(i.entity_key == "nightly_run" for i in preview.block_issues)


COLON_SKILL = """
schema_version: "0.1.0"
name: p
skills:
  - key: tiles
    name: Tiles
    content: |
      ---
      name: tiles
      description: Набор: плитка
      ---
      # Tiles
"""

BROKEN_SKILL = """
schema_version: "0.1.0"
name: p
skills:
  - key: tiles
    name: Tiles
    content: |
      ---
      name: tiles
      description: Набор: плитка
      not a key value line
      ---
      # Tiles
"""


async def test_an_unquoted_colon_in_a_skill_description_does_not_block_the_bundle():
    preview = await BundleAnalyzer().analyze(parse_bundle(COLON_SKILL))

    assert preview.installable is True
    assert skill_content_error(parse_bundle(COLON_SKILL).skills[0].content) is None


async def test_a_skill_whose_frontmatter_does_not_parse_blocks_the_bundle():
    preview = await BundleAnalyzer().analyze(parse_bundle(BROKEN_SKILL))

    assert preview.installable is False
    (issue,) = preview.block_issues
    assert issue.entity_key == "tiles"
    assert "skill 'tiles' is not a valid SKILL.md" in issue.message
    assert "line 4" in issue.message
    assert "not a key value line" in issue.message


def _signed_url_mcp(setup_type: str, spec_type: str = "url") -> str:
    spec = (
        "{type: url, endpoint_url: 'https://app.example/mcp'}"
        if spec_type == "url"
        else "{type: command, command: npx}"
    )
    return f"""
schema_version: "0.1.0"
name: p
setup:
  - {{key: signing, label: Signing key, type: {setup_type}, required: true}}
mcps:
  - key: app
    name: App
    json_spec: {spec}
    context_secret: "${{setup.signing}}"
"""


async def test_a_url_mcp_takes_its_context_secret_from_a_secret_setup_field():
    preview = await BundleAnalyzer().analyze(parse_bundle(_signed_url_mcp("secret")))
    assert preview.installable is True


async def test_a_context_secret_from_a_plain_setup_field_blocks():
    preview = await BundleAnalyzer().analyze(parse_bundle(_signed_url_mcp("string")))
    assert any("of type 'secret'" in i.message for i in preview.block_issues)


async def test_a_context_secret_on_a_command_mcp_blocks():
    preview = await BundleAnalyzer().analyze(parse_bundle(_signed_url_mcp("secret", "command")))
    assert any("url MCPs only" in i.message for i in preview.block_issues)


async def test_a_literal_context_secret_is_not_a_bundle():
    source = _signed_url_mcp("secret").replace("${setup.signing}", "x" * 40)
    with pytest.raises(BundleParseError, match="never the secret itself"):
        parse_bundle(source)


async def test_an_agent_answer_check_ships_as_a_safety_policy_on_that_agent():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: p
agents: [{key: smetchik, name: S, model: gpt-4o}]
policies:
  - key: clean_answers
    subject: smetchik
    target: content
    effect: safety
    params: {answer_check: {language: ru}}
"""
    )

    preview = await BundleAnalyzer().analyze(pkg)

    assert preview.installable is True


def test_a_merge_key_bomb_is_refused_at_its_first_alias():
    lines = ["l0: &l0 {k: x}"]
    lines += [f"l{i}: &l{i} {{<<: [*l{i - 1}, *l{i - 1}]}}" for i in range(1, 17)]

    with pytest.raises(BundleParseError, match="aliases"):
        parse_bundle("\n".join(lines))


def test_aliases_are_refused():
    with pytest.raises(BundleParseError, match="aliases"):
        parse_bundle("a: &a [x]\nb: *a\n")


def test_a_lone_surrogate_is_a_parse_error():
    with pytest.raises(BundleParseError):
        parse_bundle("name: \ud800")


CATALOG_MCP = """
schema_version: "0.1.0"
name: p
setup:
  - {key: kassa, label: Kassa token, type: secret, required: true}
  - {key: signing, label: Signing key, type: secret}
mcps:
  - key: kassa
    name: Kassa
    catalog: ru.yookassa/mcp
    bindings: {Authorization: "Bearer ${setup.kassa}"}
agents: [{key: lead, name: Lead, model: gpt-4o, mcps: [kassa]}]
"""


async def test_a_catalog_mcp_the_catalog_has_installs_as_planned():
    checks = _Checks(catalog={"ru.yookassa/mcp": "url"})
    preview = await BundleAnalyzer(checks=checks).analyze(parse_bundle(CATALOG_MCP))
    assert preview.installable is True
    assert _statuses(preview)[("mcp", "kassa")] == EntityStatus.WILL_CREATE


async def test_a_catalog_mcp_the_catalog_lacks_blocks():
    preview = await BundleAnalyzer(checks=_Checks()).analyze(parse_bundle(CATALOG_MCP))
    assert preview.installable is False
    (issue,) = preview.block_issues
    assert issue.entity_key == "kassa"
    assert "ru.yookassa/mcp" in issue.message


async def test_a_catalog_mcp_is_not_looked_up_without_a_workspace():
    preview = await BundleAnalyzer().analyze(parse_bundle(CATALOG_MCP))
    assert preview.installable is True


async def test_a_context_secret_on_a_catalog_command_server_blocks():
    source = CATALOG_MCP.replace(
        "    bindings:", '    context_secret: "${setup.signing}"\n    bindings:'
    )
    url = await BundleAnalyzer(checks=_Checks(catalog={"ru.yookassa/mcp": "url"})).analyze(
        parse_bundle(source)
    )
    command = await BundleAnalyzer(checks=_Checks(catalog={"ru.yookassa/mcp": "command"})).analyze(
        parse_bundle(source)
    )
    assert url.installable is True
    assert any("url MCPs only" in i.message for i in command.block_issues)


@pytest.mark.parametrize(
    ("spec", "error"),
    [
        ("catalog: x/y, json_spec: {type: url, url: 'https://x.test'}", "exactly one"),
        ("bindings: {}", "exactly one"),
    ],
)
async def test_an_mcp_names_a_catalog_server_or_carries_a_spec(spec, error):
    with pytest.raises(BundleParseError, match=error):
        parse_bundle('schema_version: "0.1.0"\nname: p\nmcps: [{key: m, name: M, ' + spec + "}]\n")


FILES_SKILL = """
schema_version: "0.1.0"
name: p
skills:
  - key: audit
    name: Audit
    source_type: files
    files:
      SKILL.md: "# Audit"
      scripts/run.py: "print(1)"
"""


async def test_a_files_skill_with_its_skill_md_at_the_root_installs():
    preview = await BundleAnalyzer().analyze(parse_bundle(FILES_SKILL))
    assert preview.installable is True


async def test_a_files_skill_without_a_root_skill_md_blocks():
    source = FILES_SKILL.replace('SKILL.md: "# Audit"', 'docs/SKILL.md: "# Audit"')
    preview = await BundleAnalyzer().analyze(parse_bundle(source))
    assert any("SKILL.md at the root" in i.message for i in preview.block_issues)


async def test_a_github_skill_installs_on_a_first_deploy():
    preview = await BundleAnalyzer().analyze(parse_bundle(GITHUB_SKILL))
    assert _statuses(preview)[("skill", "sk")] == EntityStatus.WILL_CREATE


async def test_a_blank_setup_value_is_not_a_supplied_one():
    prior = _prior(CHANNELED)
    preview = await BundleAnalyzer(
        existence=_Refs(), prior=prior, setup_values={"bot": " "}
    ).analyze(parse_bundle(CHANNELED))
    assert _statuses(preview)[("channel", "inbox")] == EntityStatus.UNCHANGED


async def test_a_channel_whose_type_changed_blocks():
    prior = _prior(CHANNELED)
    changed = CHANNELED.replace(
        "{key: inbox, name: Inbox,", "{key: inbox, type: generic, name: Inbox,"
    )
    preview = await BundleAnalyzer(existence=_Refs(), prior=prior).analyze(parse_bundle(changed))
    assert any(
        i.entity_key == "inbox" and "changes type" in i.message for i in preview.block_issues
    )


async def test_a_catalog_server_without_a_transport_blocks():
    checks = _Checks()
    checks.catalog = {"ru.yookassa/mcp": None}

    async def catalog_mcp(catalog_id):
        return CatalogMcp(spec_id="spec", transport=None)

    checks.catalog_mcp = catalog_mcp
    preview = await BundleAnalyzer(checks=checks).analyze(parse_bundle(CATALOG_MCP))
    assert any("declares no transport" in i.message for i in preview.block_issues)


async def test_a_supplied_value_for_a_credential_that_names_a_secret_blocks():
    prior = _prior(CHANNELED)
    analyzer = BundleAnalyzer(
        existence=_Refs(referenced={"id-inbox"}), prior=prior, setup_values={"bot": "t"}
    )
    preview = await analyzer.analyze(parse_bundle(CHANNELED))
    assert any(k == "inbox" and "bot_token" in m for k, m in _blocks(preview))

    left_out = await BundleAnalyzer(existence=_Refs(referenced={"id-inbox"}), prior=prior).analyze(
        parse_bundle(CHANNELED)
    )
    assert left_out.installable is True


CLIENT = str(UUID(int=7))


async def test_an_agent_names_its_client_by_id_and_the_workspace_checks_it():
    pkg = parse_bundle(GOOD.replace("model: gpt-4o,", f'model: gpt-4o, client: "{CLIENT}",'))
    checks = _Checks(bad_clients={CLIENT})
    preview = await BundleAnalyzer(checks=checks).analyze(pkg)
    assert any(k == "lead" and f"bad client {CLIENT}" in m for k, m in _blocks(preview))


def test_a_client_named_by_anything_but_its_id_is_refused():
    with pytest.raises(BundleParseError, match="client must be the id"):
        parse_bundle(GOOD.replace("model: gpt-4o,", "model: gpt-4o, client: my-codex,"))


async def test_a_client_from_an_optional_setup_field_left_empty_blocks():
    pkg = parse_bundle(
        GOOD.replace("setup:\n", "setup:\n  - {key: runner, label: Runner}\n", 1).replace(
            "model: gpt-4o,", 'model: gpt-4o, client: "${setup.runner}",'
        )
    )
    unset = await BundleAnalyzer(checks=_Checks()).analyze(pkg)
    given = await BundleAnalyzer(checks=_Checks(), setup_values={"runner": CLIENT}).analyze(pkg)
    assert any(k == "lead" and "client needs setup field" in m for k, m in _blocks(unset))
    assert given.installable is True


def test_reasoning_takes_one_form():
    with pytest.raises(BundleParseError, match="not both"):
        parse_bundle(
            GOOD.replace(
                "model: gpt-4o,", "model: gpt-4o, reasoning_effort: high, reasoning_max_tokens: 9,"
            )
        )


async def test_a_reasoning_change_will_update_the_agent():
    edited = DEPLOYED.replace("model: gpt-4o,", "model: gpt-4o, reasoning_effort: high,")
    preview = await BundleAnalyzer(existence=_Refs(), prior=_prior()).analyze(parse_bundle(edited))
    assert _statuses(preview)[("agent", "lead")] == EntityStatus.WILL_UPDATE


async def test_the_plan_digest_names_the_plan():
    async def digest(text, **kwargs):
        preview = await BundleAnalyzer(existence=_Refs(), prior=_prior(), **kwargs).analyze(
            parse_bundle(text)
        )
        return preview.plan_digest

    same = await digest(DEPLOYED)
    assert same == await digest(DEPLOYED)
    assert same != await digest(DEPLOYED.replace("instruction: x", "instruction: y"))
    # the same plan reaching another entity is another plan
    other = await BundleAnalyzer(existence=_Refs(), prior=_prior()).analyze(parse_bundle(DEPLOYED))
    moved = _prior()
    moved.result.entities[2] = moved.result.entities[2].model_copy(update={"id": "id-lead-2"})
    assert (
        other.plan_digest
        != (
            await BundleAnalyzer(existence=_Refs(), prior=moved).analyze(parse_bundle(DEPLOYED))
        ).plan_digest
    )


async def test_the_plan_digest_holds_only_for_the_setup_values_it_was_made_with():
    prior = _prior_with_values(MODEL_SETUP, {"model": "m1"})
    pkg = parse_bundle(MODEL_SETUP)

    async def digest(values):
        preview = await BundleAnalyzer(existence=_Refs(), prior=prior, setup_values=values).analyze(
            pkg
        )
        return preview.plan_digest

    # a first install creates the agent either way; the value it gets still differs
    fresh = await BundleAnalyzer(setup_values={"model": "m"}).analyze(pkg)
    other = await BundleAnalyzer(setup_values={"model": "other"}).analyze(pkg)
    assert {e.status for e in fresh.entities} == {e.status for e in other.entities}
    assert fresh.plan_digest != other.plan_digest
    assert await digest({"model": "m2"}) != await digest({"model": "m3"})
    assert await digest({"model": "m2"}) == await digest({"model": "m2"})


async def test_the_plan_digest_never_carries_a_secret_value():
    pkg = parse_bundle(CHANNELED)
    a = await BundleAnalyzer(setup_values={"bot": "secret-a"}).analyze(pkg)
    b = await BundleAnalyzer(setup_values={"bot": "secret-b"}).analyze(pkg)
    assert a.plan_digest == b.plan_digest


SECRET_BOUND = """
schema_version: "0.1.0"
name: p
mcps:
  - key: gh
    name: GitHub
    json_spec: {type: url, endpoint_url: "https://api.example.com/mcp"}
    bindings: {Authorization: "${secret.gh-token}"}
agents: [{key: lead, name: Lead, model: gpt-4o, mcps: [gh]}]
"""


async def test_a_secret_binding_is_planned_as_a_reference():
    checks = _Checks()
    preview = await BundleAnalyzer(checks=checks).analyze(parse_bundle(SECRET_BOUND))

    assert preview.installable is True
    assert checks.secrets_asked == ["gh-token"]
    (mcp,) = [e for e in preview.entities if e.key == "gh"]
    assert mcp.detail == "Authorization from secret 'gh-token'"
    assert preview.setup == []


async def test_a_secret_the_deployer_may_not_use_blocks():
    checks = _Checks(secret_problems={"gh-token": "is refused: you may not use it"})
    preview = await BundleAnalyzer(checks=checks).analyze(parse_bundle(SECRET_BOUND))

    assert preview.installable is False
    assert _blocks(preview) == {
        ("gh", "mcp 'gh' binding 'Authorization' is refused: you may not use it")
    }


async def test_a_secret_reference_inside_a_longer_value_blocks():
    source = SECRET_BOUND.replace('"${secret.gh-token}"', '"Bearer ${secret.gh-token}"')
    preview = await BundleAnalyzer(checks=_Checks()).analyze(parse_bundle(source))

    (issue,) = preview.block_issues
    assert "must be ${secret.<name>} alone" in issue.message
