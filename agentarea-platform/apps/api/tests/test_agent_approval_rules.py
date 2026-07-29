"""The agent editor's per-tool "requires approval" toggle is a policy rule.

The toggle used to be written into the agent's ``tools`` JSON and read back by
the display endpoint while nothing enforced it. These tests pin the translation
(config -> rule target), the idempotent sync, and the round-trip back onto the
config the UI renders.
"""

from uuid import uuid4

import pytest
from agentarea_api.api.v1._approval_policy_sync import (
    apply_approval_targets,
    approval_targets_for_agents,
    approval_targets_from_tools,
    strip_confirmation_flags,
    sync_agent_approval_rules,
)
from agentarea_common.auth.context import UserContext
from agentarea_common.base.models import BaseModel
from agentarea_common.base.repository_factory import RepositoryFactory
from agentarea_governance.application import GovernancePolicyResolver
from agentarea_governance.domain.rules import PolicyEffect, PolicySubjectType
from agentarea_governance.infrastructure.orm import PolicyRuleORM
from agentarea_governance.infrastructure.repository import PolicyRuleRepository
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


@pytest.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sync_conn: BaseModel.metadata.create_all(
                sync_conn,
                tables=[PolicyRuleORM.__table__],
            )
        )
    try:
        yield async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    finally:
        await engine.dispose()


def _context(workspace_id: str = "ws-a") -> UserContext:
    return UserContext(user_id="user-a", workspace_id=workspace_id)


def _code_tool(name: str, confirm: bool | None = None) -> dict:
    return {"name": name, "type": "code", "settings": {"requires_user_confirmation": confirm}}


def _mcp_tool(name: str, allowed: list[dict]) -> dict:
    return {"name": name, "type": "mcp", "settings": {"allowed_tools": allowed}}


# --- translation: config name -> the name the PDP actually judges ---------------


def test_code_tool_namespace_collapses_to_the_llm_facing_toolset_name():
    # Agent config carries the namespace (agentarea/shell); the model calls
    # ``shell`` and that is the only name the PDP ever sees.
    assert approval_targets_from_tools([_code_tool("agentarea/shell", True)]) == {"tool:shell"}


def test_code_tool_without_a_namespace_is_used_as_is():
    assert approval_targets_from_tools([_code_tool("shell", True)]) == {"tool:shell"}


def test_unticked_code_tool_produces_no_target():
    assert approval_targets_from_tools([_code_tool("agentarea/shell", False)]) == set()
    assert approval_targets_from_tools([_code_tool("agentarea/shell", None)]) == set()


def test_mcp_tool_name_is_the_raw_tool_name_unprefixed():
    # MCPToolFactory takes ``name`` verbatim from the server's tools/list, so the
    # allowed_tools entry and the LLM-facing name are the same string.
    tools = [
        _mcp_tool(
            "github",
            [
                {"tool_name": "create_issue", "requires_user_confirmation": True},
                {"tool_name": "list_issues", "requires_user_confirmation": False},
            ],
        )
    ]
    assert approval_targets_from_tools(tools) == {"tool:create_issue"}


def test_bare_string_allowed_tools_carry_no_confirmation():
    assert approval_targets_from_tools([_mcp_tool("github", ["create_issue"])]) == set()


def test_multiple_tools_accumulate_targets():
    tools = [
        _code_tool("agentarea/shell", True),
        _code_tool("agentarea/files", True),
        _mcp_tool("github", [{"tool_name": "create_issue", "requires_user_confirmation": True}]),
    ]
    assert approval_targets_from_tools(tools) == {
        "tool:shell",
        "tool:files",
        "tool:create_issue",
    }


# --- the flag must not survive into the persisted agent config ------------------


def test_strip_removes_the_flag_from_code_settings():
    stripped = strip_confirmation_flags([_code_tool("agentarea/shell", True)])
    assert "requires_user_confirmation" not in stripped[0]["settings"]
    assert stripped[0]["name"] == "agentarea/shell"


def test_strip_removes_the_flag_from_each_mcp_permission_but_keeps_the_tool():
    tools = [
        _mcp_tool("github", [{"tool_name": "create_issue", "requires_user_confirmation": True}])
    ]
    stripped = strip_confirmation_flags(tools)
    allowed = stripped[0]["settings"]["allowed_tools"]
    assert allowed == [{"tool_name": "create_issue"}]


def test_strip_preserves_unrelated_settings():
    tools = [
        {
            "name": "agentarea/files",
            "type": "code",
            "settings": {
                "requires_user_confirmation": True,
                "disabled_methods": ["save_file"],
            },
        }
    ]
    stripped = strip_confirmation_flags(tools)
    assert stripped[0]["settings"]["disabled_methods"] == ["save_file"]


# --- reconstitution: rules -> the config the UI renders -------------------------


def test_apply_puts_the_flag_back_on_a_code_tool():
    tools = [{"name": "agentarea/shell", "type": "code", "settings": {}}]
    applied = apply_approval_targets(tools, {"tool:shell"})
    assert applied[0]["settings"]["requires_user_confirmation"] is True


def test_apply_puts_the_flag_back_on_the_right_mcp_permission():
    tools = [
        _mcp_tool(
            "github",
            [{"tool_name": "create_issue"}, {"tool_name": "list_issues"}],
        )
    ]
    applied = apply_approval_targets(tools, {"tool:create_issue"})
    allowed = applied[0]["settings"]["allowed_tools"]
    assert allowed[0]["requires_user_confirmation"] is True
    assert allowed[1]["requires_user_confirmation"] is False


def test_strip_then_apply_round_trips_the_ui_payload():
    tools = [
        _code_tool("agentarea/shell", True),
        _mcp_tool(
            "github",
            [
                {"tool_name": "create_issue", "requires_user_confirmation": True},
                {"tool_name": "list_issues", "requires_user_confirmation": False},
            ],
        ),
    ]
    targets = approval_targets_from_tools(tools)
    restored = apply_approval_targets(strip_confirmation_flags(tools), targets)

    assert restored[0]["settings"]["requires_user_confirmation"] is True
    allowed = restored[1]["settings"]["allowed_tools"]
    assert allowed[0]["requires_user_confirmation"] is True
    assert allowed[1]["requires_user_confirmation"] is False


# --- the sync itself ------------------------------------------------------------


async def test_sync_creates_an_agent_scoped_approval_rule(session_factory):
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        await sync_agent_approval_rules(session, context, agent_id, {"tool:shell"})

        rules = await PolicyRuleRepository(session, context).list_rules(
            subject_type=PolicySubjectType.AGENT, subject_id=str(agent_id)
        )
        assert len(rules) == 1
        assert rules[0].target == "tool:shell"
        assert rules[0].effect == PolicyEffect.APPROVAL
        assert rules[0].enabled is True


async def test_sync_is_idempotent(session_factory):
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        await sync_agent_approval_rules(session, context, agent_id, {"tool:shell"})
        await sync_agent_approval_rules(session, context, agent_id, {"tool:shell"})

        rules = await PolicyRuleRepository(session, context).list_rules(
            subject_type=PolicySubjectType.AGENT, subject_id=str(agent_id)
        )
        assert len(rules) == 1


async def test_unticking_removes_the_approval(session_factory):
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        await sync_agent_approval_rules(session, context, agent_id, {"tool:shell"})
        await sync_agent_approval_rules(session, context, agent_id, set())

        assert await approval_targets_for_agents(session, context, [agent_id]) == {}


async def test_sync_reenables_a_previously_unticked_rule(session_factory):
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        await sync_agent_approval_rules(session, context, agent_id, {"tool:shell"})
        await sync_agent_approval_rules(session, context, agent_id, set())
        await sync_agent_approval_rules(session, context, agent_id, {"tool:shell"})

        assert await approval_targets_for_agents(session, context, [agent_id]) == {
            agent_id: {"tool:shell"}
        }


async def test_sync_leaves_other_agents_and_other_effects_alone(session_factory):
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        other_id = uuid4()
        repo = PolicyRuleRepository(session, context)
        await sync_agent_approval_rules(session, context, other_id, {"tool:shell"})
        await sync_agent_approval_rules(session, context, agent_id, {"tool:files"})
        await sync_agent_approval_rules(session, context, agent_id, set())

        assert await approval_targets_for_agents(session, context, [other_id]) == {
            other_id: {"tool:shell"}
        }
        spend = await repo.list_rules(
            subject_type=PolicySubjectType.AGENT, subject_id=str(agent_id)
        )
        assert spend == []


async def test_read_back_groups_targets_by_agent(session_factory):
    async with session_factory() as session:
        context = _context()
        first = uuid4()
        second = uuid4()
        await sync_agent_approval_rules(session, context, first, {"tool:shell", "tool:files"})
        await sync_agent_approval_rules(session, context, second, {"tool:create_issue"})

        assert await approval_targets_for_agents(session, context, [first, second]) == {
            first: {"tool:shell", "tool:files"},
            second: {"tool:create_issue"},
        }


# --- the whole point: the synced rule reaches the PDP verdict -------------------


async def test_a_ticked_toggle_puts_the_tool_in_escalation_rules(session_factory):
    # What this test uniquely owns: the config toggle produces the rule the
    # engine reads. That escalation_rules then drives the PDP to REQUIRE_APPROVAL
    # is proven by test_resolver_from_rules — not re-litigated here with a
    # stand-in allow rule.
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        tools = [_code_tool("agentarea/shell", True)]

        await sync_agent_approval_rules(
            session, context, agent_id, approval_targets_from_tools(tools)
        )

        resolver = GovernancePolicyResolver(RepositoryFactory(session, context))
        effective = await resolver.resolve(workspace_id=context.workspace_id, agent_id=agent_id)

        assert "shell" in effective.approval.escalation_rules


async def test_an_unticked_toggle_leaves_the_pdp_unescalated(session_factory):
    async with session_factory() as session:
        context = _context()
        agent_id = uuid4()
        tools = [_code_tool("agentarea/shell", False)]

        await sync_agent_approval_rules(
            session, context, agent_id, approval_targets_from_tools(tools)
        )

        resolver = GovernancePolicyResolver(RepositoryFactory(session, context))
        effective = await resolver.resolve(workspace_id=context.workspace_id, agent_id=agent_id)

        assert not (effective.approval.escalation_rules if effective.approval else [])
