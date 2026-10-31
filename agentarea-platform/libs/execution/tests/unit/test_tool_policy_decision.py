"""Unit tests for the unified tool-call policy decision (decide_tool_action).

Default-allow: a tool the agent is composed with runs unless policy restricts it.
The decision function only ever sees a tool the agent already offers (that is why
it is being asked about), so composition is the allow — policy carries the
subtractions: DENY, REQUIRE_APPROVAL, and (opt-in) an explicit allowlist. This
replaces the old deny-by-default, where every built-in tool needed a hand-typed
allow row just to run.
"""

from uuid import uuid4

from agentarea_execution.models import McpToolRoute, MCPToolRequest
from agentarea_execution.workflows.helpers import (
    ToolAction,
    decide_tool_action,
    filter_disclosed_tools,
    mcp_tool_restricting_aliases,
    tool_config_aliases,
    tool_policy_aliases,
    tool_policy_names,
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


def _mcp_decision(policy: dict, instance_id: str, raw_name: str = "search") -> ToolAction:
    model_name = f"mcp__server_{instance_id[:8]}__{raw_name}"
    route = McpToolRoute(instance_id=instance_id, raw_name=raw_name, attachment_ref=instance_id)
    return decide_tool_action(
        policy,
        model_name,
        tool_policy_aliases(route, model_name),
        restricting_aliases=mcp_tool_restricting_aliases(route, model_name),
    )


def test_a_server_cannot_join_an_allowlist_by_naming_its_tool_after_an_allowed_one():
    # The raw name is whatever the server advertises. Letting it satisfy an
    # allowlist meant `allowed: ["search"]`, written for one server, admitted
    # every attached server that called a tool `search`.
    trusted, other = str(uuid4()), str(uuid4())
    assert _mcp_decision({"tools": {"allowed": ["search"]}}, other) is ToolAction.DENY
    pinned = {"tools": {"allowed": [f"mcp:{trusted}:search"]}}
    assert _mcp_decision(pinned, trusted) is ToolAction.ALLOW
    assert _mcp_decision(pinned, other) is ToolAction.DENY


def test_a_bare_name_still_denies_and_escalates_every_servers_tool():
    instance_id = str(uuid4())
    assert _mcp_decision({"tools": {"denied": ["search"]}}, instance_id) is ToolAction.DENY
    escalated = {"approval": {"escalation_rules": ["search"]}}
    assert _mcp_decision(escalated, instance_id) is ToolAction.REQUIRE_APPROVAL


def _named_decision(policy: dict, tool_name: str, **sources) -> ToolAction:
    names = tool_policy_names(tool_name, **sources)
    return decide_tool_action(
        policy,
        tool_name,
        names.aliases,
        restricting_aliases=names.restricting,
        name_allows=names.name_allows,
    )


def test_a_connection_cannot_join_an_allowlist_by_taking_an_allowed_connections_name():
    # Connection names are not unique and any member may add a connection, so
    # an allowlist written for "github" admitted every connection called that.
    trusted, impostor = str(uuid4()), str(uuid4())
    model_name = "mcp__github__search"
    route = {model_name: McpToolRoute(instance_id=impostor, raw_name="search", attachment_ref="github")}
    for rule in ("mcp:github:search", model_name):
        policy = {"tools": {"allowed": [rule]}}
        assert _named_decision(policy, model_name, routes=route) is ToolAction.DENY
    pinned = {"tools": {"allowed": [f"mcp:{trusted}:search"]}}
    assert _named_decision(pinned, model_name, routes=route) is ToolAction.DENY
    own = {"tools": {"allowed": [f"mcp:{impostor}:search"]}}
    assert _named_decision(own, model_name, routes=route) is ToolAction.ALLOW


def test_a_connections_name_still_denies_and_escalates_its_tools():
    model_name = "mcp__github__search"
    route = {model_name: McpToolRoute(instance_id=str(uuid4()), raw_name="search", attachment_ref="github")}
    for rule in ("mcp:github:search", model_name, "search"):
        denied = {"tools": {"denied": [rule]}}
        assert _named_decision(denied, model_name, routes=route) is ToolAction.DENY
        escalated = {"approval": {"escalation_rules": [rule]}}
        assert _named_decision(escalated, model_name, routes=route) is ToolAction.REQUIRE_APPROVAL


def test_a_replayed_run_keeps_the_names_it_was_decided_by():
    model_name = "mcp__github__search"
    route = {model_name: McpToolRoute(instance_id=str(uuid4()), raw_name="search", attachment_ref="github")}
    policy = {"tools": {"allowed": [model_name]}}
    assert (
        _named_decision(policy, model_name, routes=route, connection_names_narrow=False)
        is ToolAction.ALLOW
    )


def test_an_openapi_operation_joins_an_allowlist_only_through_its_connection():
    # The operation name is the spec's operationId, written by whoever adds the
    # connection, so a second connection could reuse an allowed one's name.
    configs = [
        {
            "type": "openapi",
            "name": "Example Search",
            "settings": {"openapi_connection_id": "conn-1", "allowed_tools": ["search"]},
        }
    ]
    sources = {"tool_configs": configs}
    assert _named_decision({"tools": {"allowed": ["search"]}}, "search", **sources) is ToolAction.DENY
    pinned = {"tools": {"allowed": ["openapi:conn-1:search"]}}
    assert _named_decision(pinned, "search", **sources) is ToolAction.ALLOW
    assert _named_decision({"tools": {"denied": ["search"]}}, "search", **sources) is ToolAction.DENY


def test_a_platform_tool_is_still_allowed_by_its_own_name():
    assert _named_decision({"tools": {"allowed": ["shell"]}}, "shell") is ToolAction.ALLOW
