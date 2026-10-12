"""The ledger line of a platform-funded tool call, identical from a run and from /mcp."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from agentarea_governance.tool_calls import PlatformToolUsage
from agentarea_tasks.domain.costs import (
    CostCategory,
    CostSource,
    CostSubjectType,
    platform_tool_call_entry,
    tool_call_event_id,
)

TASK, AGENT, CLIENT = uuid4(), uuid4(), uuid4()
AT = datetime(2026, 10, 12, 12, tzinfo=UTC)


def _usage(**changes) -> PlatformToolUsage:
    fields = {
        "call_id": f"{TASK}:call-1",
        "workspace_id": "ws-1",
        "user_id": "alice",
        "agent_id": AGENT,
        "task_id": str(TASK),
        "client_id": None,
        "tool_name": "tools__yandex_search",
        "resource_ref": "yandex.search.web",
        "quantity": 2,
        "amount": Decimal("1.48"),
        "currency": "RUB",
        "occurred_at": AT,
    }
    return PlatformToolUsage(**{**fields, **changes})


def test_a_run_call_is_one_platform_service_line_with_its_usage_as_evidence():
    entry = platform_tool_call_entry(_usage())

    assert (entry.category, entry.source) == (CostCategory.SERVICE, CostSource.TOOL_REPORTED)
    assert (entry.subject_type, entry.subject_id) == (CostSubjectType.TOOL, "yandex.search.web")
    assert (entry.subject_name, entry.call_ref) == ("tools__yandex_search", f"{TASK}:call-1")
    assert entry.managed_by == "platform"
    assert entry.evidence == {"quantity": 2, "unit": "call", "resource_ref": "yandex.search.web"}
    assert (entry.amount, entry.currency, entry.provider_cost_usd) == (
        Decimal("1.48"),
        "RUB",
        None,
    )
    assert (entry.workspace_id, entry.created_by, entry.occurred_at) == ("ws-1", "alice", AT)
    assert (entry.task_id, entry.agent_id, entry.client_id) == (TASK, AGENT, None)
    assert entry.event_id == tool_call_event_id(f"{TASK}:call-1")


def test_a_registered_client_call_has_its_client_and_no_task():
    entry = platform_tool_call_entry(
        _usage(task_id=None, agent_id=None, client_id=str(CLIENT), call_id="mcp-call")
    )

    assert (entry.task_id, entry.agent_id, entry.client_id) == (None, None, CLIENT)


def test_the_event_id_is_the_same_for_a_retried_call_and_distinct_between_calls():
    assert tool_call_event_id("a") == tool_call_event_id("a")
    assert tool_call_event_id("a") != tool_call_event_id("b")
    assert isinstance(tool_call_event_id("a"), UUID)
