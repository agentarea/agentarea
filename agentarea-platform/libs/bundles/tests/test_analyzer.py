"""Analyzer / import-preview tests."""

import pytest
from agentarea_bundles.application.analyzer import (
    BundleAnalyzer,
    BundleParseError,
    parse_bundle,
)
from agentarea_bundles.schemas.preview import EntityStatus, IssueSeverity

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


async def test_good_package_installable():
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
    async def agent_exists(self, name):
        return True

    async def mcp_instance_exists(self, name):
        return True

    async def skill_exists(self, name):
        return True

    async def trigger_exists(self, name):
        return True


async def test_existence_marks_already_exists():
    preview = await BundleAnalyzer(existence=_AllExist()).analyze(parse_bundle(GOOD))
    statuses = {(e.kind, e.key): e.status for e in preview.entities}
    # mcp existence is by name; supported mcp should be ALREADY_EXISTS
    assert statuses[("skill", "sk")] == EntityStatus.ALREADY_EXISTS
    assert statuses[("agent", "lead")] == EntityStatus.ALREADY_EXISTS
    assert statuses[("automation", "daily")] == EntityStatus.ALREADY_EXISTS


async def test_policy_preview_entities():
    pkg = parse_bundle(
        """
schema_version: "0.1.0"
name: p
agents: [{key: lead, name: Lead, model: gpt-4o}]
policies:
  - {key: cap, subject: workspace, target: spend, effect: cap}
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


async def test_duplicate_policy_key_blocks():
    pkg = parse_bundle(
        'schema_version: "0.1.0"\nname: p\npolicies:\n'
        "  - {key: dup, subject: workspace, target: spend, effect: cap}\n"
        "  - {key: dup, subject: workspace, target: tokens, effect: cap}\n"
    )
    preview = await BundleAnalyzer().analyze(pkg)
    assert preview.installable is False
    assert any("duplicate policy key 'dup'" in i.message for i in preview.block_issues)
