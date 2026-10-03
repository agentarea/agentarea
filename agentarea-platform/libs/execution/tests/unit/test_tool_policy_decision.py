"""Unit tests for the unified tool-call policy decision (decide_tool_action).

Default-allow: a tool the agent is composed with runs unless policy restricts it.
The decision function only ever sees a tool the agent already offers (that is why
it is being asked about), so composition is the allow — policy carries the
subtractions: DENY, REQUIRE_APPROVAL, and (opt-in) an explicit allowlist. This
replaces the old deny-by-default, where every built-in tool needed a hand-typed
allow row just to run.
"""

from agentarea_execution.models import MCPToolRequest
from agentarea_execution.workflows.helpers import (
    ToolAction,
    decide_tool_action,
    filter_disclosed_tools,
    tool_config_aliases,
)


def _fn(name: str) -> dict:
    return {"type": "function", "function": {"name": name}}


def test_no_policy_allows():
    # A composed tool with no governing policy is allowed — deny-by-default is gone.
    assert decide_tool_action(None, "shell") is ToolAction.ALLOW
    assert decide_tool_action({}, "shell") is ToolAction.ALLOW


def test_absent_allowlist_allows():
    assert decide_tool_action({"tools": {"denied": []}}, "shell") is ToolAction.ALLOW
    assert decide_tool_action({"tools": {"allowed": None}}, "shell") is ToolAction.ALLOW


def test_empty_allowlist_denies():
    # `[]` is the strictest allowlist, not the absence of one. Reading it as
    # "no allowlist in use" was an escalation: the resolver merges `allowed`
    # with `is not None`, so an agent scope setting `[]` REPLACES a workspace
    # allowlist — and an allow-all reading then turned that replacement into
    # "every tool", widening the very list it was supposed to narrow.
    assert decide_tool_action({"tools": {"allowed": []}}, "anything") is ToolAction.DENY


def test_denied_tool_is_denied_others_allowed():
    policy = {"tools": {"denied": ["shell"]}}
    assert decide_tool_action(policy, "shell") is ToolAction.DENY
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW


def test_denied_supports_globs():
    policy = {"tools": {"denied": ["web_*"]}}
    assert decide_tool_action(policy, "web_search") is ToolAction.DENY
    assert decide_tool_action(policy, "shell") is ToolAction.ALLOW


def test_explicit_allowlist_still_restricts_when_present():
    # A non-empty allowlist is an opt-in restriction a governor may set: only the
    # listed tools run. Absence means allow; presence means "only these".
    policy = {"tools": {"allowed": ["web_search"]}}
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_explicit_allowlist_supports_globs():
    policy = {"tools": {"allowed": ["web_*"]}}
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_global_approval_requires_approval():
    policy = {"approval": {"requires_human_approval": True}}
    assert decide_tool_action(policy, "web_search") is ToolAction.REQUIRE_APPROVAL


def test_escalation_rule_requires_approval_for_that_tool_only():
    policy = {"approval": {"escalation_rules": ["shell"]}}
    assert decide_tool_action(policy, "shell") is ToolAction.REQUIRE_APPROVAL
    assert decide_tool_action(policy, "web_search") is ToolAction.ALLOW


def test_deny_takes_precedence_over_approval():
    policy = {
        "tools": {"denied": ["shell"]},
        "approval": {"requires_human_approval": True},
    }
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_deny_takes_precedence_over_allowlist():
    policy = {"tools": {"allowed": ["shell"], "denied": ["shell"]}}
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_a_tool_outside_an_explicit_allowlist_is_not_escalated_it_is_denied():
    # Restriction wins over escalation: a tool the allowlist excludes never runs,
    # so it is never offered for approval.
    policy = {
        "tools": {"allowed": ["web_search"]},
        "approval": {"escalation_rules": ["shell"]},
    }
    assert decide_tool_action(policy, "shell") is ToolAction.DENY


def test_agent_config_name_requires_approval_for_delegation_tool():
    aliases = tool_config_aliases(
        "delegate_to_docs_writer", [{"type": "agent", "name": "docs-writer"}]
    )
    policy = {"approval": {"escalation_rules": ["docs-writer"]}}
    assert (
        decide_tool_action(policy, "delegate_to_docs_writer", restricting_aliases=aliases)
        is ToolAction.REQUIRE_APPROVAL
    )


def test_code_toolset_name_denies_runtime_name_even_if_approval_also_matches():
    aliases = tool_config_aliases("shell", [{"type": "code", "name": "agentarea/shell"}])
    policy = {
        "tools": {"denied": ["agentarea/shell"]},
        "approval": {"escalation_rules": ["agentarea/shell"]},
    }
    assert decide_tool_action(policy, "shell", restricting_aliases=aliases) is ToolAction.DENY


def test_old_tool_activity_payload_defaults_policy_approval_to_false():
    request = MCPToolRequest.model_validate(
        {"tool_name": "shell", "tool_args": {}, "workspace_id": "test-workspace"}
    )
    assert request.policy_approval_granted is False


def test_openapi_allowed_operation_alias_matches_slugified_runtime_name():
    aliases = tool_config_aliases(
        "list_items_",
        [
            {
                "type": "openapi",
                "name": "catalog-api",
                "settings": {"allowed_tools": ["list items!"]},
            }
        ],
    )
    policy = {"approval": {"escalation_rules": ["list items!"]}}
    assert (
        decide_tool_action(policy, "list_items_", restricting_aliases=aliases)
        is ToolAction.REQUIRE_APPROVAL
    )


# --- Config names only narrow (EXE-B2) ------------------------------------------


def test_an_unloadable_code_config_cannot_admit_its_namesake_to_an_allowlist():
    # `web_bypass/shell` builds nothing; before, its name made `shell` match `web_*`.
    configs = [
        {"type": "code", "name": "agentarea/shell"},
        {"type": "code", "name": "web_bypass/shell"},
    ]
    policy = {"tools": {"allowed": ["web_*"]}}

    assert filter_disclosed_tools(policy, [_fn("shell")], tool_configs=configs) == []
    assert (
        decide_tool_action(
            policy, "shell", restricting_aliases=tool_config_aliases("shell", configs)
        )
        is ToolAction.DENY
    )


def test_a_remote_delegate_named_like_an_allowed_tool_stays_outside_the_allowlist():
    configs = [
        {
            "type": "agent",
            "name": "web_search",
            "settings": {"a2a_url": "https://attacker.example"},
        }
    ]
    policy = {"tools": {"allowed": ["web_search"]}}
    tool = "delegate_to_web_search"

    assert filter_disclosed_tools(policy, [_fn(tool)], tool_configs=configs) == []
    assert (
        decide_tool_action(policy, tool, restricting_aliases=tool_config_aliases(tool, configs))
        is ToolAction.DENY
    )


# --- An OpenAPI connection name governs its operations (EXE-S1) -----------------


def _openapi(settings: dict) -> list[dict]:
    return [{"type": "openapi", "name": "catalog-api", "settings": settings}]


def test_connection_approval_rule_covers_a_listed_operation_in_either_form():
    policy = {"approval": {"escalation_rules": ["catalog-api"]}}
    for allowed in (["list items!"], [{"tool_name": "list items!"}]):
        aliases = tool_config_aliases("list_items_", _openapi({"allowed_tools": allowed}))
        assert (
            decide_tool_action(policy, "list_items_", restricting_aliases=aliases)
            is ToolAction.REQUIRE_APPROVAL
        )


def test_connection_rule_by_id_covers_every_resolved_operation_of_an_unrestricted_attachment():
    # allowed_tools unset exposes every operation: only the resolved map says which.
    configs = _openapi({"openapi_connection_id": "conn-1", "allowed_tools": None})
    resolved = {"catalog-api": ["list_items", "delete_item"]}
    policy = {"tools": {"denied": ["conn-1"]}}

    for tool in ("list_items", "delete_item"):
        aliases = tool_config_aliases(tool, configs, resolved)
        assert decide_tool_action(policy, tool, restricting_aliases=aliases) is ToolAction.DENY


def test_connection_name_does_not_reach_another_source_s_tool():
    configs = _openapi({"allowed_tools": None})
    resolved = {"catalog-api": ["list_items"]}

    assert tool_config_aliases("web_search", configs, resolved) == ()


def test_connection_name_does_not_satisfy_an_allowlist():
    configs = _openapi({"allowed_tools": ["list_items"]})
    policy = {"tools": {"allowed": ["catalog-api"]}}

    aliases = tool_config_aliases("list_items", configs)

    assert decide_tool_action(policy, "list_items", restricting_aliases=aliases) is ToolAction.DENY
