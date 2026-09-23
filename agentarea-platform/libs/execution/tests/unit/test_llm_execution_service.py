"""One-call results, accounting, and stream ownership across the Temporal boundary."""

import asyncio
from contextlib import asynccontextmanager, suppress
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID

import pytest
from agentarea_agents_sdk.models.llm_model import LLMResponse, LLMUsage
from agentarea_common.auth.context import UserContext
from agentarea_common.money import to_money
from agentarea_execution import llm_execution_service
from agentarea_execution.exceptions import ModelInstanceNotFoundError
from agentarea_execution.models import LLMCallRequest, ResolvedModelInfo
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
                **overrides,
            }
        )

    return build


@pytest.fixture
def model_scope():
    record = SimpleNamespace(
        id=UUID(MODEL_ID),
        provider_config=SimpleNamespace(
            provider_spec=SimpleNamespace(provider_type="openai"),
            endpoint_url="http://localhost:8000/provider/v1",
            api_key=None,
            managed_by=None,
        ),
        model_spec=SimpleNamespace(
            model_name="database-model",
            endpoint_url="http://localhost:9000/spec/v1",
            max_output_tokens=2000,
            input_cost_per_token=0.001,
            output_cost_per_token=0.002,
        ),
    )
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
        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
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


async def test_cached_secret_failure_falls_back_to_fresh_model_resolution(
    provider, make_service, model_scope, secret_store, user_context
):
    request = _request()
    reference = "stale-reference"
    request.resolved_model["api_key_secret"] = reference
    model_scope.record.provider_config.api_key = "fresh-reference"  # pragma: allowlist secret
    secret_store.store.get_secret.side_effect = [RuntimeError("stale secret"), "fresh-key"]

    result = await make_service(
        model_service_scope=model_scope.scope, secret_manager_factory=secret_store.factory
    ).execute(request, user_context=user_context)

    assert result.content == "hello"
    assert model_scope.contexts == [user_context]
    assert provider.constructor.call_args.kwargs["api_key"] == "fresh-key"  # pragma: allowlist secret
    assert provider.constructor.call_args.kwargs["model_name"] == "database-model"
    assert "fresh-key" not in result.model_dump_json()
    assert secret_store.session.close.await_count == 2


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
                    usage=_usage(),
                    cost=0.5,
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
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
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


@pytest.fixture
def activity_boundary(monkeypatch):
    from agentarea_execution.activities import agent_execution_activities as activities
    from agentarea_execution.activities import dependencies

    # The cached-model route never needs the container's database-backed services.
    monkeypatch.setattr(dependencies, "ActivityServiceContainer", Mock())
    injected = SimpleNamespace(
        settings=SimpleNamespace(app=SimpleNamespace(local_host="127.0.0.1")),
        secret_manager_factory=Mock(
            create=Mock(side_effect=AssertionError("keyless activity must not read secrets"))
        ),
        event_broker=SimpleNamespace(publish=AsyncMock()),
        broker_client=None,
    )
    enriched_error = AsyncMock()
    monkeypatch.setattr(activities, "publish_enriched_llm_error_event", enriched_error)
    functions = {fn.__name__: fn for fn in activities.make_agent_activities(injected)}
    return SimpleNamespace(
        call=functions["call_llm_activity"], errors=enriched_error, dependencies=injected
    )


def _activity_request(**overrides):
    return _request(task_id="task-1", agent_id="agent-1", execution_id="execution-1", **overrides)


async def test_activity_maps_missing_usage_to_nonretryable_error_once(provider, activity_boundary):
    provider.chunks = [_response("unaccounted")]
    request = _activity_request()

    with pytest.raises(ApplicationError) as raised:
        await ActivityEnvironment().run(activity_boundary.call, request)

    assert raised.value.non_retryable is True
    assert raised.value.type == "RuntimeError"
    assert isinstance(raised.value.__cause__, RuntimeError)
    activity_boundary.errors.assert_awaited_once_with(
        error=raised.value.__cause__,
        task_id="task-1",
        agent_id="agent-1",
        execution_id="execution-1",
        model_id=MODEL_ID,
        provider_type="openai",
        event_broker=activity_boundary.dependencies.event_broker,
    )


async def test_activity_preserves_retryable_rate_limit_and_publishes_error_once(
    provider, activity_boundary
):
    original = RuntimeError("rate limit exceeded")
    provider.ainvoke_stream.side_effect = original

    with pytest.raises(ApplicationError) as raised:
        await ActivityEnvironment().run(activity_boundary.call, _activity_request())

    assert raised.value.non_retryable is False
    assert raised.value.type == "RuntimeError"
    assert raised.value.__cause__ is original
    activity_boundary.errors.assert_awaited_once()
    assert activity_boundary.errors.call_args.kwargs["error"] is original
    assert activity_boundary.errors.call_args.kwargs["provider_type"] == "openai"
    provider.ainvoke_stream.assert_called_once()
    provider.complete.assert_not_awaited()


async def test_activity_context_failure_publishes_once_without_calling_provider(
    provider, activity_boundary
):
    with pytest.raises(ApplicationError) as raised:
        await ActivityEnvironment().run(
            activity_boundary.call, _activity_request(user_context_data=None)
        )

    assert raised.value.type == "ValueError"
    activity_boundary.errors.assert_awaited_once()
    assert activity_boundary.errors.call_args.kwargs["error"] is raised.value.__cause__
    assert activity_boundary.errors.call_args.kwargs["provider_type"] is None
    provider.ainvoke_stream.assert_not_called()
    provider.complete.assert_not_awaited()
