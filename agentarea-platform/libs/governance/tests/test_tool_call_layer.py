"""The one layer every tool call passes, from a run or from /mcp.

In order: the policy verdict (the runtime PDP); for a call on a platform-funded
connection its price and the entitlement gate; the call; and for such a call that ran,
one line handed to the caller's spend ledger. A refused call never reaches the vendor,
and nothing is recorded for a call that did not run.
"""

from decimal import Decimal
from uuid import UUID

import pytest
from agentarea_common.auth.tool_authorization import (
    ToolAuthorizationAction,
    ToolAuthorizationRequest,
)
from agentarea_common.extensions import customer_pricing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_governance.domain.enums import InterceptorAction, InterceptorCategory, Phase
from agentarea_governance.domain.models import InterceptorResult
from agentarea_governance.tool_calls import (
    GovernedToolCall,
    PlatformFundedTool,
    ToolCallOutcome,
    Verdict,
    entitlement_guard,
    run_tool_call,
)

AGENT = UUID(int=7)


class Ledger:
    def __init__(self, raises=False):
        self.lines = []
        self.raises = raises

    async def __call__(self, usage):
        if self.raises:
            raise RuntimeError("db down")
        self.lines.append(usage)


class Guard:
    name = "entitlement_guard"
    category = InterceptorCategory.GATE

    def __init__(self, action=InterceptorAction.ALLOW, reason="ok"):
        self.action, self.reason = action, reason
        self.contexts = []

    async def execute(self, context):
        self.contexts.append(context)
        return InterceptorResult(
            action=self.action, interceptor_name=self.name, reason=self.reason
        )


class Vendor:
    def __init__(self, success=True, quantity=1):
        self.calls = 0
        self.success, self.quantity = success, quantity

    async def __call__(self):
        self.calls += 1
        return ToolCallOutcome(success=self.success, usage_quantity=self.quantity, value="data")


class Audit:
    def __init__(self):
        self.decisions = []

    async def __call__(self, decision):
        self.decisions.append(decision)


class Pricing(customer_pricing.ProviderCostPricing):
    def currency(self) -> str:
        return "RUB"

    async def price_tool_call(self, resource_ref: str) -> Decimal:
        if resource_ref != "yandex.search.web":
            raise LookupError(f"no price for {resource_ref}")
        return Decimal("0.74")


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.setattr(customer_pricing, "get_customer_pricing", lambda: Pricing())
    ExtensionRegistry.clear()
    entitlement_guard.cache_clear()
    yield
    ExtensionRegistry.clear()
    entitlement_guard.cache_clear()


def _install(guard=None):
    guard = guard or Guard()
    ExtensionRegistry.register("entitlement_guard", lambda: guard)
    return guard


def _call(
    *, paid="yandex.search.web", policy=None, approved=False, task_id="task-1", client_id=None
):
    return GovernedToolCall(
        authorization=ToolAuthorizationRequest(
            tool_name="gateway__yandex_search",
            tool_args={"query": "agentarea"},
            user_id="runner",
            workspace_id="ws-1",
            effective_policy=policy,
        ),
        call_id="call-9",
        agent_id=AGENT,
        task_id=task_id,
        client_id=client_id,
        platform_funded=PlatformFundedTool(paid) if paid is not None else None,
        approval_granted=approved,
    )


async def test_a_paid_call_is_priced_gated_then_runs_then_writes_one_ledger_line():
    guard = _install()
    vendor, audit, ledger = Vendor(quantity=2), Audit(), Ledger()

    result = await run_tool_call(_call(), vendor, audit=audit, ledger=ledger)

    assert result.verdict is Verdict.RAN
    assert result.outcome.value == "data"
    assert vendor.calls == 1
    [context] = guard.contexts
    assert context.phase is Phase.PRE_TOOL_CALL
    assert (context.workspace_id, context.user_id, context.agent_id) == ("ws-1", "runner", AGENT)
    assert context.execution_state["paid_call"] == {
        "resource_ref": "yandex.search.web",
        "managed_by": "platform",
    }
    [usage] = ledger.lines
    assert usage == result.usage
    assert (usage.call_id, usage.workspace_id, usage.user_id) == ("call-9", "ws-1", "runner")
    assert (usage.agent_id, usage.task_id, usage.client_id) == (AGENT, "task-1", None)
    assert (usage.tool_name, usage.resource_ref, usage.quantity) == (
        "gateway__yandex_search",
        "yandex.search.web",
        2,
    )
    assert (usage.amount, usage.currency) == (Decimal("1.48"), "RUB")
    assert [d.action for d in audit.decisions] == [ToolAuthorizationAction.ALLOW]


async def test_a_call_from_a_registered_client_names_it_and_no_task():
    _install()
    ledger = Ledger()

    await run_tool_call(
        _call(task_id=None, client_id="client-1"), Vendor(), audit=Audit(), ledger=ledger
    )

    [usage] = ledger.lines
    assert (usage.task_id, usage.client_id) == (None, "client-1")


async def test_no_balance_refuses_before_the_vendor_is_called():
    _install(guard=Guard(InterceptorAction.DENY, "no credits remaining"))
    vendor, audit, ledger = Vendor(), Audit(), Ledger()

    result = await run_tool_call(_call(), vendor, audit=audit, ledger=ledger)

    assert result.verdict is Verdict.DENIED
    assert "no credits remaining" in result.decision.reason
    assert vendor.calls == 0
    assert ledger.lines == []
    assert [d.action for d in audit.decisions] == [ToolAuthorizationAction.DENY]


async def test_an_unpriced_paid_tool_is_refused_before_billing_is_asked():
    """No fallback: a platform-funded call nobody is charged for is not made."""
    guard = _install()
    vendor, audit = Vendor(), Audit()

    result = await run_tool_call(
        _call(paid="yandex.search.images"), vendor, audit=audit, ledger=Ledger()
    )

    assert result.verdict is Verdict.DENIED
    assert "no price" in result.decision.reason
    assert guard.contexts == [] and vendor.calls == 0
    assert [d.action for d in audit.decisions] == [ToolAuthorizationAction.DENY]


async def test_a_platform_tool_that_declares_no_resource_is_refused():
    guard = _install()
    vendor = Vendor()

    result = await run_tool_call(_call(paid=""), vendor, audit=Audit(), ledger=Ledger())

    assert result.verdict is Verdict.DENIED
    assert "declares no metered resource" in result.decision.reason
    assert guard.contexts == [] and vendor.calls == 0


async def test_policy_denies_before_billing_is_asked():
    guard = _install()
    vendor = Vendor()

    result = await run_tool_call(
        _call(policy={"tools": {"denied": ["gateway__*"]}}), vendor, audit=Audit(), ledger=Ledger()
    )

    assert result.verdict is Verdict.DENIED
    assert guard.contexts == []
    assert vendor.calls == 0


async def test_a_held_call_waits_for_its_approval_and_then_runs():
    _install()
    policy = {"approval": {"escalation_rules": ["gateway__*"]}}
    vendor, ledger = Vendor(), Ledger()

    held = await run_tool_call(_call(policy=policy), vendor, audit=Audit(), ledger=ledger)
    ran = await run_tool_call(
        _call(policy=policy, approved=True), vendor, audit=Audit(), ledger=ledger
    )

    assert held.verdict is Verdict.HELD
    assert ran.verdict is Verdict.RAN
    assert vendor.calls == 1
    assert len(ledger.lines) == 1


async def test_a_free_call_asks_nobody_and_records_nothing():
    guard = _install()
    vendor, ledger = Vendor(), Ledger()

    result = await run_tool_call(_call(paid=None), vendor, audit=Audit(), ledger=ledger)

    assert result.verdict is Verdict.RAN
    assert result.usage is None
    assert guard.contexts == [] and ledger.lines == []


async def test_a_paid_call_with_no_gate_is_refused():
    vendor = Vendor()

    result = await run_tool_call(_call(), vendor, audit=Audit(), ledger=Ledger())

    assert result.verdict is Verdict.DENIED
    assert "entitlement" in result.decision.reason
    assert vendor.calls == 0


async def test_a_failed_call_records_nothing():
    _install()
    ledger = Ledger()

    result = await run_tool_call(_call(), Vendor(success=False), audit=Audit(), ledger=ledger)

    assert result.verdict is Verdict.RAN
    assert result.usage is None and ledger.lines == []


async def test_a_call_that_reports_no_usage_records_nothing(caplog):
    _install()
    ledger = Ledger()

    await run_tool_call(_call(), Vendor(quantity=None), audit=Audit(), ledger=ledger)

    assert ledger.lines == []
    assert "reported no usage" in caplog.text


async def test_a_failed_ledger_write_is_logged_and_the_result_still_returned(caplog):
    _install()

    result = await run_tool_call(_call(), Vendor(), audit=Audit(), ledger=Ledger(raises=True))

    assert result.verdict is Verdict.RAN
    assert result.outcome.value == "data"
    assert "was not recorded" in caplog.text
