"""One-call results, accounting, and stream ownership across the Temporal boundary."""

import asyncio
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from uuid import uuid4
from agentarea_agents_sdk.models.llm_model import LLMResponse, LLMUsage
from agentarea_agents_sdk.models.provider_profiles import ProviderProfile
from agentarea_common.auth.context import UserContext
from agentarea_common.money import to_money
from agentarea_execution import llm_execution_service
from agentarea_execution.exceptions import ModelInstanceNotFoundError
from agentarea_execution.models import LLMCallRequest, ResolvedModelInfo
from agentarea_llm.domain.models import ModelInstance
from temporalio.exceptions import ApplicationError
from temporalio.testing import ActivityEnvironment

MODEL_ID = "00000000-0000-0000-0000-000000000001"
pytestmark = pytest.mark.asyncio


def _response(content="", **kwargs):
    return LLMResponse(content=content, role="assistant", **kwargs)


def _usage():
    return LLMUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15)


def _tool(arguments):
    return {
        "id": "call-1",
        "type": "function",
        "function": {"name": "lookup", "arguments": arguments},
    }


def _request(**overrides):
    cached = ResolvedModelInfo(
        model_id=MODEL_ID,
        provider_type="openai",
        provider=ProviderProfile(base_url="https://api.openai.com/v1").as_mapping(),
        model_name="test-model",
        context_window=32000,
        max_output_tokens=2000,
        input_cost_per_token=0.001,
        output_cost_per_token=0.002,
        api_key_secret=None,
    )
    return LLMCallRequest(
        **{
            "model_id": MODEL_ID,
            "messages": [{"role": "user", "content": "Hello"}],
            "resolved_model": cached.model_dump(),
            "user_context_data": {
                "user_id": "test-user",
                "workspace_id": "test-workspace",
                "agent_id": "agent-1",
            },
            "effective_policy": {"tokens": {"max_tokens_per_call": 1000}},
            **overrides,
        }
    )


class _Progress:
    def __init__(self):
        self.events = []

    async def __call__(self, chunk, chunk_index, is_final=False, chunk_type="text"):
        self.events.append((chunk, chunk_index, is_final, chunk_type))


@pytest.fixture
def user_context():
    return UserContext(user_id="test-user", workspace_id="test-workspace")


@pytest.fixture
def provider(monkeypatch):
    boundary = SimpleNamespace(
        chunks=[_response("hello", usage=_usage(), cost=0.02)],
        complete=AsyncMock(return_value=_response("hello", usage=_usage(), cost=0.02)),
    )

    async def stream(request):
        for response in boundary.chunks:
            yield response

    boundary.ainvoke_stream = Mock(side_effect=stream)
    boundary.constructor = Mock(return_value=boundary)
    monkeypatch.setattr(llm_execution_service, "LLMModel", boundary.constructor)
    return boundary


@pytest.fixture
def make_service():
    def build(**overrides):
        return llm_execution_service.LLMExecutionService(
            **{
                "model_service_scope": Mock(
                    side_effect=AssertionError("cached calls must not read model records")
                ),
                "secret_manager_factory": Mock(
                    create=Mock(side_effect=AssertionError("keyless calls must not read secrets"))
                ),
                "local_host": "127.0.0.1",
                "refuse_at_spend_cap": AsyncMock(),
                **overrides,
            }
        )

    return build


@pytest.fixture
def model_scope():
    record = SimpleNamespace(
        id=UUID(MODEL_ID),
        workspace_id="ws-model",
        provider_config=SimpleNamespace(
            provider_spec=SimpleNamespace(
                provider_type="openai",
                profile=lambda: ProviderProfile(base_url="https://api.openai.com/v1"),
            ),
            endpoint_url="http://localhost:8000/provider/v1",
            api_key=None,
            managed_by=None,
            workspace_id="ws-model",
        ),
        model_spec=SimpleNamespace(
            model_name="database-model",
            endpoint_url="http://localhost:9000/spec/v1",
            max_output_tokens=2000,
            input_cost_per_token=0.001,
            output_cost_per_token=0.002,
            workspace_id="ws-model",
        ),
    )
    record.foreign_part = lambda: ModelInstance.foreign_part(record)  # type: ignore[arg-type]
    state = SimpleNamespace(
        record=record,
        service=SimpleNamespace(get=AsyncMock(return_value=record)),
        contexts=[],
        is_open=False,
        closed=False,
    )

    @asynccontextmanager
    async def scope(context):
        state.contexts.append(context)
        state.is_open = True
        try:
            yield state.service
        finally:
            state.is_open = False
            state.closed = True

    state.scope = scope
    return state


@pytest.fixture
def secret_store(monkeypatch):
    session = SimpleNamespace(close=AsyncMock())
    monkeypatch.setattr(
        "agentarea_common.config.get_database",
        lambda: SimpleNamespace(async_session_factory=lambda: session),
    )
    store = SimpleNamespace(get_secret=AsyncMock(return_value=None))
    return SimpleNamespace(
        factory=Mock(create=Mock(return_value=store)), store=store, session=session
    )


async def test_trailing_metadata_and_cumulative_tools_produce_one_final_result(
    provider, make_service, user_context
):
    provider.chunks = [
        _response("hel", reasoning_content="why", tool_calls=[_tool('{"x":')], cost=0.01),
        _response("lo", tool_calls=[_tool('{"x":1}')]),
        _response(usage=_usage()),
        _response(cost=0.02),
        _response(cost=0.005),
    ]
    progress = _Progress()
    service = make_service()

    result = await service.execute(_request(), user_context=user_context, on_chunk=progress)
    without_sink = await service.execute(_request(), user_context=user_context)

    assert result.model_dump() == {
        "role": "assistant",
        "content": "hello",
        "thinking": "why",
        "tool_calls": [_tool('{"x":1}')],
        "cost": "0.02",
        "provider_cost_usd": "0.02",
        "currency": "USD",
        "managed_by": None,
        "usage": {
            "prompt_tokens": 10,
            "completion_tokens": 5,
            "total_tokens": 15,
            "cached_prompt_tokens": 0,
            "cache_creation_tokens": 0,
            "billing": {
                "amount": "0.02",
                "currency": "USD",
                "vendor_cost": "0.02",
                "vendor_currency": "USD",
                "estimate": False,
                "settle": None,
                "hold_id": None,
                "cost_unknown": False,
                "payer": "workspace",
                "model_instance_id": MODEL_ID,
            },
        },
        "interrupted": False,
        "finish_reason": None,
    }
    assert result.cost == to_money("0.02")
    assert without_sink == result
    assert progress.events == [
        ("why", 0, False, "thinking"),
        ("hel", 1, False, "text"),
        ("lo", 2, False, "text"),
        ("", 3, True, "text"),
    ]
    assert provider.ainvoke_stream.call_count == 2
    provider.complete.assert_not_awaited()


async def test_nonstreamed_completion_has_result_parity_without_publishing_progress(
    provider, make_service, user_context
):
    complete = _response(
        "hello", reasoning_content="why", tool_calls=[_tool('{"x":1}')], usage=_usage(), cost=0.02
    )
    provider.chunks = [complete]
    provider.complete.return_value = complete
    streamed_progress, complete_progress = _Progress(), _Progress()

    streamed = await make_service(stream=True).execute(
        _request(), user_context=user_context, on_chunk=streamed_progress
    )
    completed = await make_service(stream=False).execute(
        _request(), user_context=user_context, on_chunk=complete_progress
    )

    assert completed == streamed
    assert completed.content == "hello"
    assert completed.thinking == "why"
    assert completed.tool_calls == [_tool('{"x":1}')]
    assert completed.usage.total_tokens == 15
    assert completed.cost == to_money("0.02")
    assert complete_progress.events == []
    assert streamed_progress.events[-1] == ("", 2, True, "text")
    provider.ainvoke_stream.assert_called_once()
    provider.complete.assert_awaited_once()


@pytest.mark.parametrize("stream", [True, False], ids=["streamed", "completed"])
@pytest.mark.parametrize("usage", [None, LLMUsage()], ids=["missing", "zero"])
async def test_unaccounted_response_fails_without_success_marker_or_retry(
    provider, make_service, user_context, stream, usage
):
    response = _response("unaccounted", usage=usage)
    provider.chunks = [response]
    provider.complete.return_value = response
    progress, errors = _Progress(), AsyncMock()

    with pytest.raises(RuntimeError, match="LLM usage accounting unavailable") as raised:
        await make_service(stream=stream).execute(
            _request(), user_context=user_context, on_chunk=progress, on_error=errors
        )

    assert not any(event[2] for event in progress.events)
    errors.assert_awaited_once_with(raised.value, "openai")
    assert provider.ainvoke_stream.call_count == int(stream)
    assert provider.complete.await_count == int(not stream)


@pytest.mark.parametrize("missing_rate", ["input_cost_per_token", "output_cost_per_token"])
async def test_unknown_pricing_rejects_before_provider_io(
    provider, make_service, user_context, missing_rate
):
    request = _request()
    request.resolved_model[missing_rate] = None

    with pytest.raises(ValueError, match="model pricing is not configured"):
        await make_service().execute(request, user_context=user_context)

    provider.ainvoke_stream.assert_not_called()
    provider.complete.assert_not_awaited()


@pytest.mark.parametrize("stream", [True, False], ids=["streamed", "completed"])
async def test_priced_free_tool_only_response_succeeds(
    provider, make_service, user_context, stream
):
    request = _request()
    request.resolved_model.update(input_cost_per_token=0, output_cost_per_token=0)
    response = _response(tool_calls=[_tool('{"x":1}')], usage=_usage(), cost=0)
    provider.chunks = [response]
    provider.complete.return_value = response

    result = await make_service(stream=stream).execute(request, user_context=user_context)

    assert result.content == ""
    assert result.tool_calls == [_tool('{"x":1}')]
    assert result.usage.total_tokens == 15
    assert result.cost == to_money("0")


async def test_cached_prompt_tokens_reach_the_result_and_the_model_gets_the_cached_rate(
    provider, make_service, user_context
):
    request = _request()
    request.resolved_model.update(cached_input_cost_per_token="0.0001")
    usage = LLMUsage(
        prompt_tokens=1000,
        completion_tokens=100,
        total_tokens=1100,
        cached_prompt_tokens=800,
        cache_creation_tokens=50,
    )
    provider.chunks = [_response("hello", usage=usage, cost=0.48)]

    result = await make_service().execute(request, user_context=user_context)

    assert provider.constructor.call_args.kwargs["cached_input_cost_per_token"] == to_money(
        "0.0001"
    )
    assert (result.usage.cached_prompt_tokens, result.usage.cache_creation_tokens) == (800, 50)


async def test_uncached_model_scope_closes_before_using_provider_config_endpoint(
    provider, make_service, model_scope, user_context
):
    async def stream(request):
        assert model_scope.closed
        assert not model_scope.is_open
        yield _response("database answer", usage=_usage(), cost=0.02)

    provider.ainvoke_stream.side_effect = stream
    result = await make_service(
        model_service_scope=model_scope.scope, local_host="model-host"
    ).execute(_request(resolved_model=None), user_context=user_context)

    assert result.content == "database answer"
    assert model_scope.contexts == [user_context]
    model_scope.service.get.assert_awaited_once_with(UUID(MODEL_ID))
    config = provider.constructor.call_args.kwargs
    assert config["endpoint_url"] == "http://model-host:8000/provider/v1"
    assert config["model_name"] == "database-model"


async def test_missing_cached_secret_stays_keyless_without_database_fallback(
    provider, make_service, secret_store, user_context
):
    request = _request()
    reference = "unset-reference"
    request.resolved_model["api_key_secret"] = reference

    result = await make_service(secret_manager_factory=secret_store.factory).execute(
        request, user_context=user_context
    )

    assert result.content == "hello"
    assert provider.constructor.call_args.kwargs["api_key"] is None
    secret_store.session.close.assert_awaited_once()


async def test_cached_model_without_provider_type_uses_database_resolution(
    provider, make_service, model_scope, user_context
):
    request = _request()
    request.resolved_model.pop("provider_type")

    result = await make_service(model_service_scope=model_scope.scope).execute(
        request, user_context=user_context
    )

    assert result.content == "hello"
    assert model_scope.contexts == [user_context]
    assert provider.constructor.call_args.kwargs["model_name"] == "database-model"


async def test_missing_model_raises_domain_error_and_closes_scope(
    provider, make_service, model_scope, user_context
):
    model_scope.service.get.return_value = None

    with pytest.raises(ModelInstanceNotFoundError):
        await make_service(model_service_scope=model_scope.scope).execute(
            _request(resolved_model=None), user_context=user_context
        )

    assert model_scope.closed
    assert not model_scope.is_open
    provider.ainvoke_stream.assert_not_called()
    provider.complete.assert_not_awaited()


@pytest.mark.parametrize("part", ["provider_config", "model_spec"])
async def test_database_resolution_refuses_a_part_from_another_workspace(
    provider, make_service, model_scope, user_context, part
):
    getattr(model_scope.record, part).workspace_id = "ws-attacker-owned"

    with pytest.raises(ModelInstanceNotFoundError, match=part):
        await make_service(model_service_scope=model_scope.scope).execute(
            _request(resolved_model=None), user_context=user_context
        )

    provider.constructor.assert_not_called()
    provider.ainvoke_stream.assert_not_called()


@pytest.mark.parametrize("cancel_at", ["provider", "callback"])
async def test_cancellation_closes_iterator_and_next_call_has_no_partial_state(
    provider, make_service, user_context, cancel_at
):
    waiting, closed, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    progress, errors = _Progress(), AsyncMock()
    invocation = 0

    async def stream(request):
        nonlocal invocation
        invocation += 1
        if invocation == 1:
            try:
                yield _response(
                    "old",
                    reasoning_content="old reasoning",
                    tool_calls=[_tool('{"old":1}')],
                )
                waiting.set()
                await release.wait()
            finally:
                closed.set()
        else:
            yield _response("fresh", usage=_usage(), cost=0.02)

    async def on_chunk(chunk, chunk_index, is_final=False, chunk_type="text"):
        await progress(chunk, chunk_index, is_final, chunk_type)
        if cancel_at == "callback":
            waiting.set()
            await release.wait()

    provider.ainvoke_stream.side_effect = stream
    service = make_service()
    task = asyncio.create_task(
        service.execute(_request(), user_context=user_context, on_chunk=on_chunk, on_error=errors)
    )
    try:
        await asyncio.wait_for(waiting.wait(), timeout=2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await asyncio.wait_for(task, timeout=2)
        assert closed.is_set()
        assert not any(event[2] for event in progress.events)
        errors.assert_not_awaited()
        result = await asyncio.wait_for(
            service.execute(_request(), user_context=user_context), timeout=2
        )
        assert result.model_dump() == {
            "role": "assistant",
            "content": "fresh",
            "thinking": "",
            "tool_calls": None,
            "cost": "0.02",
            "provider_cost_usd": "0.02",
            "currency": "USD",
            "managed_by": None,
            "usage": {
                "prompt_tokens": 10,
                "completion_tokens": 5,
                "total_tokens": 15,
                "cached_prompt_tokens": 0,
                "cache_creation_tokens": 0,
                "billing": {
                    "amount": "0.02",
                    "currency": "USD",
                    "vendor_cost": "0.02",
                    "vendor_currency": "USD",
                    "estimate": False,
                    "settle": None,
                    "hold_id": None,
                    "cost_unknown": False,
                    "payer": "workspace",
                    "model_instance_id": MODEL_ID,
                },
            },
            "interrupted": False,
            "finish_reason": None,
        }
        assert result.cost == to_money("0.02")
    finally:
        release.set()
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def test_chunk_callback_failure_closes_iterator_and_reports_original_error(
    provider, make_service, user_context
):
    closed = asyncio.Event()
    original = RuntimeError("chunk delivery failed")
    errors = AsyncMock()

    async def stream(request):
        try:
            yield _response("partial")
            yield _response(usage=_usage())
        finally:
            closed.set()

    provider.ainvoke_stream.side_effect = stream
    with pytest.raises(RuntimeError) as raised:
        await make_service().execute(
            _request(),
            user_context=user_context,
            on_chunk=AsyncMock(side_effect=original),
            on_error=errors,
        )

    assert raised.value is original
    assert closed.is_set()
    errors.assert_awaited_once_with(original, "openai")


async def test_error_publication_failure_does_not_replace_provider_error(
    provider, make_service, user_context
):
    original = RuntimeError("provider unavailable")
    provider.complete.side_effect = original
    errors = AsyncMock(side_effect=ValueError("error publication failed"))

    with pytest.raises(RuntimeError) as raised:
        await make_service(stream=False).execute(
            _request(), user_context=user_context, on_error=errors
        )

    assert raised.value is original
    errors.assert_awaited_once_with(original, "openai")
    provider.complete.assert_awaited_once()
    provider.ainvoke_stream.assert_not_called()


class _Billing:
    """Billing in EUR: holds 19 EUR per call, prices the platform's 1 USD at 142.5."""

    def __init__(self, *, allowed=True, quote_fails=False):
        self.allowed, self.quote_fails = allowed, quote_fails
        self.authorizations, self.quotes, self.voids = [], [], []

    def currency(self):
        return "EUR"

    async def authorize(self, **request):
        self.authorizations.append(request)
        return SimpleNamespace(
            allowed=self.allowed,
            code="ok" if self.allowed else "no_credits",
            reason="" if self.allowed else "no credits remaining",
            hold_id="hold-1" if self.allowed else None,
            amount=to_money("19.00") if self.allowed else None,
            currency="EUR",
            expires_at=None,
        )

    async def capture(self, **request):
        raise AssertionError("the settlement worker captures")

    async def void(self, *, hold_id):
        self.voids.append(hold_id)

    async def quote(self, lines):
        self.quotes.extend(lines)
        if self.quote_fails:
            raise ConnectionError("billing down")
        factor = to_money("142.5") if lines[0].payer == "platform" else to_money(95)
        return [SimpleNamespace(amount=line.vendor_cost * factor, code="ok") for line in lines]


@pytest.fixture
def billing(monkeypatch):
    from agentarea_common.extensions import tool_billing
    from agentarea_common.extensions.registry import ExtensionRegistry

    installed = _Billing()
    monkeypatch.setattr(tool_billing, "get_spend_currency", lambda: "EUR")
    monkeypatch.setattr(ExtensionRegistry, "_factories", {"tool_billing": lambda: installed})
    tool_billing.get_tool_billing.cache_clear()
    yield installed
    tool_billing.get_tool_billing.cache_clear()


@pytest.mark.parametrize("stream", [True, False], ids=["streamed", "completed"])
async def test_a_platform_call_is_held_and_its_line_is_billings_price(
    billing, provider, make_service, user_context, stream
):
    request = _request()
    request.resolved_model["managed_by"] = "platform"

    result = await make_service(stream=stream).execute(request, user_context=user_context)

    [hold] = billing.authorizations
    assert (hold["kind"], hold["tool"], hold["vendor_currency"]) == ("model", MODEL_ID, "USD")
    assert hold["vendor_cost"] > to_money("0.02")
    assert (result.cost, result.currency) == (to_money("2.85"), "EUR")
    assert result.provider_cost_usd == to_money("0.02")
    assert result.usage.billing["hold_id"] == "hold-1"
    assert result.usage.billing["settle"] == "capture"
    assert billing.voids == []


async def test_a_customer_key_call_holds_nothing_and_is_converted_without_markup(
    billing, provider, make_service, user_context
):
    result = await make_service().execute(_request(), user_context=user_context)

    assert billing.authorizations == []
    assert (result.cost, result.currency) == (to_money("1.90"), "EUR")
    assert result.usage.billing["hold_id"] is None


async def test_no_credits_refuses_the_call_before_the_provider_is_asked(
    billing, provider, make_service, user_context
):
    from agentarea_common.model_charges import ModelCallRefusedError

    billing.allowed = False
    request = _request()
    request.resolved_model["managed_by"] = "platform"

    with pytest.raises(ModelCallRefusedError, match="no_credits"):
        await make_service().execute(request, user_context=user_context)

    provider.ainvoke_stream.assert_not_called()


async def test_a_call_past_a_monthly_llm_cap_is_refused_before_it_is_held(
    billing, provider, make_service, user_context
):
    from agentarea_tasks.model_spend_caps import SpendCapReachedError

    refuse = AsyncMock(side_effect=SpendCapReachedError("Workspace monthly LLM spend cap reached"))
    request = _request()
    request.resolved_model["managed_by"] = "platform"

    with pytest.raises(SpendCapReachedError):
        await make_service(refuse_at_spend_cap=refuse).execute(request, user_context=user_context)

    refuse.assert_awaited_once_with(request, user_context)
    assert billing.authorizations == []
    provider.ainvoke_stream.assert_not_called()


async def test_a_failed_platform_call_voids_its_hold(billing, provider, make_service, user_context):
    provider.ainvoke_stream.side_effect = RuntimeError("provider down")
    request = _request()
    request.resolved_model["managed_by"] = "platform"

    with pytest.raises(RuntimeError, match="provider down"):
        await make_service().execute(request, user_context=user_context)

    assert billing.voids == ["hold-1"]


async def test_billing_unable_to_price_keeps_the_hold_on_the_line(
    billing, provider, make_service, user_context
):
    billing.quote_fails = True
    request = _request()
    request.resolved_model["managed_by"] = "platform"

    result = await make_service().execute(request, user_context=user_context)

    assert (result.cost, result.currency) == (to_money("19.00"), "EUR")
    assert result.usage.billing["settle"] == "capture"


async def test_a_platform_credential_is_read_only_after_billing_holds_the_call(
    billing, provider, make_service, secret_store, user_context
):
    order = []
    authorize = billing.authorize

    async def recorded_authorize(**request):
        order.append("hold")
        return await authorize(**request)

    async def read_secret(name):
        order.append("credential")
        return "platform-key"

    billing.authorize = recorded_authorize
    secret_store.store.get_secret.side_effect = read_secret
    request = _request()
    request.resolved_model.update(managed_by="platform", api_key_secret="platform-openai")

    result = await make_service(secret_manager_factory=secret_store.factory).execute(
        request, user_context=user_context
    )

    assert order == ["hold", "credential"]
    assert provider.constructor.call_args.kwargs["api_key"] == "platform-key"
    assert result.usage.billing["payer"] == "platform"


async def test_a_refused_hold_never_reads_the_platform_credential(
    billing, provider, make_service, secret_store, user_context
):
    from agentarea_common.model_charges import ModelCallRefusedError

    billing.allowed = False
    request = _request()
    request.resolved_model.update(managed_by="platform", api_key_secret="platform-openai")

    with pytest.raises(ModelCallRefusedError, match="no_credits"):
        await make_service(secret_manager_factory=secret_store.factory).execute(
            request, user_context=user_context
        )

    secret_store.factory.create.assert_not_called()
    secret_store.store.get_secret.assert_not_awaited()
    provider.constructor.assert_not_called()


async def test_a_credential_that_cannot_be_read_voids_the_hold_and_fails_the_call(
    billing, provider, make_service, model_scope, secret_store, user_context
):
    """No second lookup: a held call whose key cannot be read does not run."""
    original = RuntimeError("secret cannot be decrypted")
    secret_store.store.get_secret.side_effect = original
    request = _request()
    request.resolved_model.update(managed_by="platform", api_key_secret="platform-openai")

    with pytest.raises(RuntimeError) as raised:
        await make_service(
            model_service_scope=model_scope.scope, secret_manager_factory=secret_store.factory
        ).execute(request, user_context=user_context)

    assert raised.value is original
    assert billing.voids == ["hold-1"]
    assert model_scope.contexts == []
    secret_store.store.get_secret.assert_awaited_once_with("platform-openai")
    secret_store.session.close.assert_awaited_once()
    provider.constructor.assert_not_called()


@pytest.fixture
def activity_boundary(monkeypatch):
    from agentarea_execution.activities import agent_execution_activities as activities
    from agentarea_execution.activities import dependencies

    from agentarea_execution.activities.agent import llm as llm_activities

    # The cached-model route never needs the container's database-backed services.
    monkeypatch.setattr(dependencies, "ActivityServiceContainer", Mock())
    container = dependencies.ActivityServiceContainer.return_value
    container._database.async_session_factory.return_value = AsyncMock()

    class _Tasks:
        def __init__(self, session, user_context):
            pass

        async def get_task(self, task_id):
            return SimpleNamespace(id=task_id, agent_id=uuid4())

    async def caps_as_the_run_froze_them(session, user_context, agent_id, run_budget):
        return run_budget

    monkeypatch.setattr(llm_activities, "TaskRepository", _Tasks)
    monkeypatch.setattr(llm_activities, "current_budget", caps_as_the_run_froze_them)
    injected = SimpleNamespace(
        settings=SimpleNamespace(app=SimpleNamespace(local_host="127.0.0.1")),
        secret_manager_factory=Mock(
            create=Mock(side_effect=AssertionError("keyless activity must not read secrets"))
        ),
        event_broker=SimpleNamespace(publish=AsyncMock()),
        broker_client=None,
    )
    functions = {fn.__name__: fn for fn in activities.make_agent_activities(injected)}
    return SimpleNamespace(call=functions["call_llm_activity"], dependencies=injected)


def _activity_request(**overrides):
    return _request(
        task_id=str(uuid4()), agent_id=str(uuid4()), execution_id="execution-1", **overrides
    )


async def test_activity_maps_missing_usage_to_nonretryable_error_once(provider, activity_boundary):
    provider.chunks = [_response("unaccounted")]
    request = _activity_request()

    with pytest.raises(ApplicationError) as raised:
        await ActivityEnvironment().run(activity_boundary.call, request)

    assert raised.value.non_retryable is True
    assert raised.value.type == "RuntimeError"
    assert isinstance(raised.value.__cause__, RuntimeError)


async def test_activity_preserves_retryable_rate_limit(provider, activity_boundary):
    original = RuntimeError("rate limit exceeded")
    provider.ainvoke_stream.side_effect = original

    with pytest.raises(ApplicationError) as raised:
        await ActivityEnvironment().run(activity_boundary.call, _activity_request())

    assert raised.value.non_retryable is False
    assert raised.value.type == "RuntimeError"
    assert raised.value.__cause__ is original
    provider.ainvoke_stream.assert_called_once()
    provider.complete.assert_not_awaited()


async def test_activity_context_failure_never_calls_the_provider(provider, activity_boundary):
    with pytest.raises(ApplicationError) as raised:
        await ActivityEnvironment().run(
            activity_boundary.call, _activity_request(user_context_data=None)
        )

    assert raised.value.type == "ValueError"
    provider.ainvoke_stream.assert_not_called()
    provider.complete.assert_not_awaited()


async def test_compaction_is_held_and_priced_like_the_loop_calls(
    monkeypatch, billing, provider, activity_boundary
):
    """Compaction spends the same run budget, so it is billed the same way."""
    from agentarea_execution.activities import agent_execution_activities as activities
    from agentarea_execution.activities.agent import llm as llm_activities
    from agentarea_execution.models import CompactMessagesRequest, ConversationWindow
    from agentarea_tasks.domain.models import ConversationEntry

    log = [ConversationEntry(seq=0, role="system", content="system")] + [
        ConversationEntry(seq=seq, role="user", content=f"turn {seq}") for seq in range(1, 7)
    ]
    written: list = []

    async def sync_window(container, user_context, window, pending):
        return log[:1], log[1:], len(log)

    async def write_entries(container, user_context, task_id, entries):
        written.extend(entries)

    monkeypatch.setattr(llm_activities.conversation_log, "sync_window", sync_window)
    monkeypatch.setattr(llm_activities.conversation_log, "write_entries", write_entries)
    monkeypatch.setattr(llm_activities, "LLMModel", provider.constructor)
    functions = {
        fn.__name__: fn for fn in activities.make_agent_activities(activity_boundary.dependencies)
    }
    request = _request()
    request.resolved_model["managed_by"] = "platform"

    result = await ActivityEnvironment().run(
        functions["compact_messages_activity"],
        CompactMessagesRequest(
            conversation=ConversationWindow(
                task_id=str(uuid4()), head_seqs=[0], tail_start=1, next_seq=7
            ),
            keep_recent=2,
            model_id=MODEL_ID,
            workspace_id="test-workspace",
            user_context_data=request.user_context_data,
            resolved_model=request.resolved_model,
            effective_policy=request.effective_policy,
        ),
    )

    assert result.cost == to_money("2.85")
    assert result.usage.billing["hold_id"] == "hold-1"
    assert result.original_message_count == 4
    assert result.conversation.head_seqs == [0, 7]
    assert result.conversation.tail_start == 5
    assert [entry.kind for entry in written] == ["compaction"]
    [hold] = billing.authorizations
    assert (hold["kind"], hold["tool"]) == ("model", MODEL_ID)


async def test_a_stop_after_the_provider_reported_usage_returns_what_was_billed(
    provider, make_service, user_context
):
    """A reply cut short still cost what the provider reported; that is not lost."""
    waiting, release = asyncio.Event(), asyncio.Event()

    async def stream(request):
        yield _response("partial", usage=_usage(), cost=0.5)
        waiting.set()
        await release.wait()

    provider.ainvoke_stream.side_effect = stream
    task = asyncio.create_task(make_service().execute(_request(), user_context=user_context))
    await asyncio.wait_for(waiting.wait(), timeout=2)
    task.cancel()
    result = await asyncio.wait_for(task, timeout=2)

    assert result.interrupted is True
    assert result.content == "partial"
    assert result.cost == to_money("0.5")
    assert result.usage is not None and result.usage.total_tokens == 15


LLM_CAP = {"amount_usd": "2", "category": "llm", "own_agent": True}
CAPPED_AGENT = uuid4()


@pytest.fixture
def llm_cap_reached(monkeypatch, activity_boundary):
    """Every monthly LLM cap read reports the cap reached; the reads are recorded."""
    from agentarea_execution.activities.agent import llm as llm_activities
    from agentarea_tasks.model_spend_caps import SpendCapReachedError

    reads: list = []

    class _Tasks:
        def __init__(self, session, user_context):
            pass

        async def get_task(self, task_id):
            return SimpleNamespace(id=task_id, agent_id=CAPPED_AGENT)

    async def refuse(session, user_context, budget, agent_id):
        reads.append(([cap.amount_usd for cap in budget.spend_caps or []], agent_id))
        raise SpendCapReachedError("Agent monthly LLM spend cap reached (2 EUR/2 EUR)")

    monkeypatch.setattr(llm_activities, "TaskRepository", _Tasks)
    monkeypatch.setattr(llm_activities, "refuse_model_call_at_spend_cap", refuse)
    return reads


def _assert_refused_at_the_cap(raised) -> None:
    assert raised.value.type == "SpendCapReachedError"
    assert raised.value.non_retryable is True
    assert raised.value.message == "Agent monthly LLM spend cap reached (2 EUR/2 EUR)"


async def test_a_turn_past_a_monthly_llm_cap_is_refused_as_a_spend_cap_stop(
    billing, provider, activity_boundary, llm_cap_reached
):
    request = _request(
        task_id=str(uuid4()),
        agent_id=str(CAPPED_AGENT),
        effective_policy={
            "tokens": {"max_tokens_per_call": 1000},
            "budget": {"spend_caps": [LLM_CAP]},
        },
    )
    request.resolved_model["managed_by"] = "platform"

    with pytest.raises(ApplicationError) as raised:
        await ActivityEnvironment().run(activity_boundary.call, request)

    _assert_refused_at_the_cap(raised)
    assert llm_cap_reached == [([to_money("2")], CAPPED_AGENT)]
    assert billing.authorizations == []
    provider.ainvoke_stream.assert_not_called()


async def test_a_turn_under_only_a_workspace_monthly_cap_reads_it_before_the_call(
    billing, provider, activity_boundary, llm_cap_reached
):
    request = _request(
        task_id=str(uuid4()),
        agent_id=str(CAPPED_AGENT),
        effective_policy={
            "tokens": {"max_tokens_per_call": 1000},
            "budget": {"monthly_spend_cap_usd": "10"},
        },
    )
    request.resolved_model["managed_by"] = "platform"

    with pytest.raises(ApplicationError) as raised:
        await ActivityEnvironment().run(activity_boundary.call, request)

    _assert_refused_at_the_cap(raised)
    assert llm_cap_reached == [([], CAPPED_AGENT)]
    provider.ainvoke_stream.assert_not_called()


async def test_a_compaction_past_a_monthly_llm_cap_is_refused_as_a_spend_cap_stop(
    monkeypatch, billing, provider, activity_boundary, llm_cap_reached
):
    """Compaction is a model call of the run: the cap the run's agent reached refuses it."""
    from agentarea_execution.activities import agent_execution_activities as activities
    from agentarea_execution.activities.agent import llm as llm_activities
    from agentarea_execution.models import CompactMessagesRequest, ConversationWindow
    from agentarea_tasks.domain.models import ConversationEntry

    log = [ConversationEntry(seq=0, role="system", content="system")] + [
        ConversationEntry(seq=seq, role="user", content=f"turn {seq}") for seq in range(1, 7)
    ]

    async def sync_window(container, user_context, window, pending):
        return log[:1], log[1:], len(log)

    monkeypatch.setattr(llm_activities.conversation_log, "sync_window", sync_window)
    monkeypatch.setattr(llm_activities, "LLMModel", provider.constructor)
    functions = {
        fn.__name__: fn for fn in activities.make_agent_activities(activity_boundary.dependencies)
    }
    request = _request()
    request.resolved_model["managed_by"] = "platform"

    with pytest.raises(ApplicationError) as raised:
        await ActivityEnvironment().run(
            functions["compact_messages_activity"],
            CompactMessagesRequest(
                conversation=ConversationWindow(
                    task_id=str(uuid4()), head_seqs=[0], tail_start=1, next_seq=7
                ),
                keep_recent=2,
                model_id=MODEL_ID,
                workspace_id="test-workspace",
                user_context_data=request.user_context_data,
                resolved_model=request.resolved_model,
                effective_policy={
                    "tokens": {"max_tokens_per_call": 1000},
                    "budget": {"spend_caps": [LLM_CAP]},
                },
            ),
        )

    _assert_refused_at_the_cap(raised)
    assert llm_cap_reached == [([to_money("2")], CAPPED_AGENT)]
    assert billing.authorizations == []
    provider.constructor.assert_not_called()


@pytest.mark.parametrize(("spec_flag", "reads"), [(True, True), (False, False), (None, False)])
async def test_only_the_spec_flag_says_a_model_reads_images(spec_flag, reads):
    assert llm_execution_service.model_reads_images(spec_flag) is reads
