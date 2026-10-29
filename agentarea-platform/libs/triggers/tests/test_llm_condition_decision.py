"""A decision-kind model answers a trigger condition as a yes/no question; chat keeps its path.

Either way the call is funded before its credential is read and written to the ledger
(wiki ADR-0038).
"""

from dataclasses import fields
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from agentarea_agents_sdk.models.llm_model import LLMResponse, LLMUsage
from agentarea_agents_sdk.models.provider_profiles import ProviderProfile
from agentarea_common.auth.context import UserContext
from agentarea_common.extensions import tool_billing
from agentarea_common.extensions.registry import ExtensionRegistry
from agentarea_common.model_charges import ModelCallRefusedError
from agentarea_common.tool_cost import Payer
from agentarea_llm.infrastructure.model_clients import ModelEndpoint, ModelTarget
from agentarea_tasks.domain.costs import CostCategory, CostSubjectType
from agentarea_tasks.model_spend_caps import SpendCapReachedError
from agentarea_triggers.llm_condition_evaluator import (
    LLMConditionEvaluationError,
    LLMConditionEvaluator,
)

MODEL = uuid4()
CONDITION = {
    "type": "llm",
    "description": "the customer is asking for a refund",
    "model_id": str(MODEL),
}
EVENT = {"message": "I want my money back"}
WORKSPACE = "ws-1"


class Billing:
    def __init__(self, *, allowed=True, code="ok"):
        self.allowed, self.code = allowed, code
        self.authorizations, self.quotes, self.voids = [], [], []

    def currency(self):
        return "EUR"

    async def authorize(self, **request):
        self.authorizations.append(request)
        return SimpleNamespace(
            allowed=self.allowed,
            code=self.code,
            reason="no credits remaining" if not self.allowed else "",
            hold_id="hold-1" if self.allowed else None,
            amount=Decimal("19.00") if self.allowed else None,
            currency="EUR",
            expires_at=None,
        )

    async def capture(self, **request):
        raise AssertionError("the settlement worker captures")

    async def void(self, *, hold_id):
        self.voids.append(hold_id)

    async def quote(self, lines):
        self.quotes.extend(lines)
        return [SimpleNamespace(amount=line.vendor_cost * 150, code="ok") for line in lines]


@pytest.fixture(autouse=True)
def rub_deployment_without_billing(monkeypatch):
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "EUR")
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()
    yield
    ExtensionRegistry.clear()
    tool_billing.get_tool_billing.cache_clear()


def _install(billing: Billing) -> Billing:
    ExtensionRegistry.register("tool_billing", lambda: billing)
    tool_billing.get_tool_billing.cache_clear()
    return billing


def _instances(kind: str):
    service = AsyncMock()
    instance = MagicMock()
    instance.model_spec.kind = kind
    service.get.return_value = instance
    return service


class _Models:
    def __init__(self, choice: str = "true", *, managed_by: str | None = None, cost_usd=0):
        self.choice = choice
        self.managed_by = managed_by
        self.cost_usd = cost_usd
        self.asked: list = []
        self.funded: list = []

    async def describe(self, instance_id, kind):
        return ModelTarget(
            instance_id=str(instance_id),
            provider_type="openai",
            provider=ProviderProfile(base_url="https://api.openai.com/v1"),
            model_name="gpt-4",
            endpoint_url=None,
            managed_by=self.managed_by,
            input_cost_per_token=Decimal("0.00001"),
            output_cost_per_token=Decimal("0.00003"),
            max_output_tokens=100,
        )

    async def connect(self, target, funding):
        self.funded.append(funding)
        return ModelEndpoint(
            **{f.name: getattr(target, f.name) for f in fields(target)},
            api_key="sk-resolved",  # pragma: allowlist secret
        )

    async def decision_model(self, target, funding):
        self.funded.append(funding)

        async def evaluate(state, questions):
            self.asked.append((target.instance_id, state, questions))
            return SimpleNamespace(
                answers={"condition_met": {"type": "choice", "choice": self.choice}},
                cost_usd=self.cost_usd,
            )

        return SimpleNamespace(evaluate=evaluate)


class _Ledger:
    def __init__(self):
        self.lines: list = []

    async def __call__(self, lines):
        self.lines.extend(lines)
        return len(lines)


def _evaluator(
    kind: str,
    models: _Models,
    ledger: _Ledger | None = None,
    refuse_at_spend_cap: AsyncMock | None = None,
) -> LLMConditionEvaluator:
    return LLMConditionEvaluator(
        model_instance_service=_instances(kind),
        secret_manager=MagicMock(),
        model_service=models,
        user_context=UserContext(user_id="user-1", workspace_id=WORKSPACE),
        record_costs=ledger or _Ledger(),
        refuse_at_spend_cap=refuse_at_spend_cap or AsyncMock(),
    )


COMPLETE = "agentarea_agents_sdk.models.llm_model.LLMModel.complete"


async def _verdict(model, _request) -> LLMResponse:
    usage = LLMUsage(prompt_tokens=100, completion_tokens=20, total_tokens=120)
    return LLMResponse(
        content='{"verdict": "met", "score": 0.9, "reason": "refund"}',
        role="assistant",
        usage=usage,
        cost=model._configured_cost(usage),
    )


@pytest.mark.parametrize("choice, expected", [("true", True), ("false", False)])
async def test_a_decision_model_answers_the_condition(choice, expected):
    models = _Models(choice)

    with patch(COMPLETE, autospec=True) as chat:
        met = await _evaluator("decision", models).evaluate_condition(CONDITION, EVENT)

    assert met is expected
    chat.assert_not_called()
    [(instance_id, state, questions)] = models.asked
    assert instance_id == str(MODEL)
    assert state["event"] == EVENT
    assert questions == {
        "condition_met": {
            "type": "choice",
            "instructions": "Is this condition met by the event: the customer is asking for a refund",
            "criteria": {
                "true": "The event meets the condition",
                "false": "The event does not meet the condition",
            },
        }
    }


async def test_a_chat_model_keeps_the_completion_path():
    models = _Models()

    with patch(COMPLETE, autospec=True, side_effect=_verdict) as chat:
        met = await _evaluator("chat", models).evaluate_condition(CONDITION, EVENT)

    assert met is True
    chat.assert_awaited_once()
    model = chat.await_args.args[0]
    assert model.api_key == "sk-resolved"  # pragma: allowlist secret
    assert (model.provider_type, model.model_name) == ("openai", "gpt-4")
    assert models.asked == []


async def test_a_media_model_cannot_evaluate_a_condition():
    with pytest.raises(LLMConditionEvaluationError, match="image"):
        await _evaluator("image", _Models()).evaluate_condition(CONDITION, EVENT)


async def test_a_condition_without_its_own_model_is_refused():
    condition = {"type": "llm", "description": "the customer is asking for a refund"}

    with pytest.raises(LLMConditionEvaluationError, match="model_id"):
        await _evaluator("chat", _Models()).evaluate_condition(condition, EVENT)


async def test_each_sub_condition_uses_its_own_model():
    models = _Models()
    first, second = uuid4(), uuid4()
    combined = {
        "type": "combined",
        "logic": "AND",
        "conditions": [
            {**CONDITION, "model_id": str(first)},
            {**CONDITION, "model_id": str(second)},
        ],
    }

    assert await _evaluator("decision", models).evaluate_condition(combined, EVENT) is True
    assert [instance_id for instance_id, _, _ in models.asked] == [str(first), str(second)]


async def test_a_chat_condition_on_the_platforms_key_is_held_before_the_call():
    billing = _install(Billing())
    models = _Models(managed_by="platform")
    ledger = _Ledger()

    with patch(COMPLETE, autospec=True, side_effect=_verdict) as chat:
        met = await _evaluator("chat", models, ledger).evaluate_condition(
            CONDITION, EVENT, {"trigger_id": "trigger-1"}
        )

    assert met is True
    chat.assert_awaited_once()
    [request] = billing.authorizations
    assert (request["workspace_id"], request["kind"], request["tool"]) == (
        WORKSPACE,
        "model",
        str(MODEL),
    )
    assert request["vendor_cost"] > 0
    [funding] = models.funded
    assert funding.hold_id == "hold-1"
    [line] = ledger.lines
    assert (line.category, line.subject_type, line.subject_id) == (
        CostCategory.MODEL,
        CostSubjectType.MODEL_INSTANCE,
        str(MODEL),
    )
    assert line.task_id is None
    assert line.payer == Payer.PLATFORM
    assert line.currency == "EUR"
    assert line.evidence["hold_id"] == "hold-1"
    assert line.evidence["settle"] == "capture"
    assert line.evidence["purpose"] == "trigger_condition"
    assert line.evidence["trigger_id"] == "trigger-1"
    assert billing.voids == []


async def test_a_refused_hold_never_reaches_the_provider():
    _install(Billing(allowed=False, code="no_credits"))
    models = _Models(managed_by="platform")
    ledger = _Ledger()

    with (
        patch(COMPLETE, autospec=True) as chat,
        pytest.raises(LLMConditionEvaluationError) as refused,
    ):
        await _evaluator("chat", models, ledger).evaluate_condition(CONDITION, EVENT)

    assert isinstance(refused.value.__cause__, ModelCallRefusedError)
    assert refused.value.__cause__.code == "no_credits"
    chat.assert_not_called()
    assert models.funded == []
    assert ledger.lines == []


@pytest.mark.parametrize("kind", ["chat", "decision"])
async def test_a_condition_past_a_monthly_llm_cap_never_reaches_the_model(kind):
    billing = _install(Billing())
    models = _Models(managed_by="platform")
    ledger = _Ledger()
    agent_id = uuid4()
    refuse = AsyncMock(
        side_effect=SpendCapReachedError("Workspace monthly LLM spend cap reached (2 EUR/2 EUR)")
    )

    with (
        patch(COMPLETE, autospec=True) as chat,
        pytest.raises(LLMConditionEvaluationError) as refused,
    ):
        await _evaluator(kind, models, ledger, refuse).evaluate_condition(
            CONDITION, EVENT, {"trigger_id": "trigger-1", "agent_id": str(agent_id)}
        )

    assert isinstance(refused.value.__cause__, SpendCapReachedError)
    assert "spend_cap_reached" in str(refused.value)
    refuse.assert_awaited_once_with(agent_id)
    chat.assert_not_called()
    assert billing.authorizations == []
    assert models.funded == []
    assert models.asked == []
    assert ledger.lines == []


async def test_a_refused_hold_never_asks_a_decision_model():
    _install(Billing(allowed=False, code="no_credits"))
    models = _Models(managed_by="platform")

    with pytest.raises(LLMConditionEvaluationError, match="no_credits"):
        await _evaluator("decision", models).evaluate_condition(CONDITION, EVENT)

    assert models.funded == []
    assert models.asked == []


async def test_a_decision_condition_writes_one_model_line_carrying_its_hold():
    billing = _install(Billing())
    models = _Models(managed_by="platform", cost_usd=Decimal("0.002"))
    ledger = _Ledger()

    met = await _evaluator("decision", models, ledger).evaluate_condition(
        CONDITION, EVENT, {"trigger_id": "trigger-1"}
    )

    assert met is True
    assert len(billing.authorizations) == 1
    [line] = ledger.lines
    assert (line.category, line.subject_type, line.subject_id, line.task_id) == (
        CostCategory.MODEL,
        CostSubjectType.MODEL_INSTANCE,
        str(MODEL),
        None,
    )
    assert line.payer == Payer.PLATFORM
    assert line.evidence["hold_id"] == "hold-1"
    assert line.evidence["trigger_id"] == "trigger-1"
    assert (line.amount, line.currency) == (Decimal("0.300"), "EUR")
    assert (line.vendor_cost, line.provider_cost_usd) == (Decimal("0.002"), Decimal("0.002"))
    assert billing.voids == []


async def test_a_provider_failure_voids_the_hold():
    billing = _install(Billing())
    models = _Models(managed_by="platform")
    ledger = _Ledger()

    with (
        patch(COMPLETE, autospec=True, side_effect=RuntimeError("provider down")),
        pytest.raises(LLMConditionEvaluationError),
    ):
        await _evaluator("chat", models, ledger).evaluate_condition(CONDITION, EVENT)

    assert billing.voids == ["hold-1"]
    assert ledger.lines == []
