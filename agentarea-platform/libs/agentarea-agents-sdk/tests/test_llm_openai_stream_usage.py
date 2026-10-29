"""OpenAI-compatible streaming usage/cost accounting."""

import json
from decimal import Decimal

import pytest

from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest
from agentarea_agents_sdk.models.provider_profiles import ProviderProfile

OPENAI = ProviderProfile(base_url="https://api.openai.com/v1")


class _Response:
    status_code = 200

    async def aiter_lines(self):
        yield "data: " + json.dumps(
            {
                "choices": [
                    {
                        "delta": {"content": "hello"},
                    }
                ]
            }
        )
        # OpenAI emits include_usage as a final chunk with an empty choices list.
        yield "data: " + json.dumps(
            {
                "choices": [],
                "usage": {
                    "prompt_tokens": 10,
                    "completion_tokens": 5,
                    "total_tokens": 15,
                },
            }
        )
        yield "data: [DONE]"

    async def aclose(self):
        return None

    def raise_for_status(self):
        return None


class _Client:
    last_json = None

    def __init__(self, **_kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def build_request(self, _method, _url, *, json, headers):  # noqa: ARG002
        type(self).last_json = json
        return object()

    async def send(self, _request, *, stream):  # noqa: ARG002
        return _Response()


@pytest.mark.asyncio
async def test_usage_only_final_chunk_is_not_dropped(monkeypatch):
    from agentarea_agents_sdk.models import llm_model as module

    monkeypatch.setattr(module.httpx, "AsyncClient", _Client)
    model = LLMModel(
        provider_type="openai",
        model_name="custom-model",
        endpoint_url="https://example.invalid/v1",
        input_cost_per_token=0.001,
        output_cost_per_token=0.002,
    )

    chunks = [
        chunk
        async for chunk in model._stream_openai_compatible(
            LLMRequest(messages=[{"role": "user", "content": "hi"}])
        )
    ]

    assert chunks[0].content == "hello"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 15
    assert chunks[-1].cost == Decimal("0.02")
    assert _Client.last_json["stream_options"] == {"include_usage": True}


def _serve_sse(monkeypatch, model, events, captured, status=200, body=None):
    """Point the model's HTTP client at a fake server answering with these SSE events."""
    from agentarea_agents_sdk.models import llm_model as module

    def handle(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        if status >= 400:
            return module.httpx.Response(status, json=body or {})
        text = "".join(f"data: {json.dumps(event)}\n\n" for event in events)
        return module.httpx.Response(200, text=text + "data: [DONE]\n\n")

    monkeypatch.setattr(
        model,
        "_http_client",
        lambda timeout: module.httpx.AsyncClient(transport=module.httpx.MockTransport(handle)),
    )


@pytest.mark.asyncio
async def test_a_provider_without_endpoint_url_is_called_at_its_public_address(monkeypatch):
    model = LLMModel(
        provider_type="openrouter",
        provider=ProviderProfile(base_url="https://openrouter.ai/api/v1"),
        model_name="vendor/new-model",
        api_key="k",
        input_cost_per_token=0.001,
        output_cost_per_token=0.002,
    )
    captured: dict = {}
    _serve_sse(
        monkeypatch,
        model,
        [
            {"choices": [{"delta": {"content": "hello"}}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        ],
        captured,
    )

    chunks = [
        chunk
        async for chunk in model.ainvoke_stream(
            LLMRequest(messages=[{"role": "user", "content": "hi"}])
        )
    ]

    assert captured["url"] == "https://openrouter.ai/api/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer k"
    assert captured["json"]["stream_options"] == {"include_usage": True}
    assert chunks[0].content == "hello"
    assert chunks[-1].usage is not None
    assert chunks[-1].usage.total_tokens == 15
    assert chunks[-1].cost == Decimal("0.02")


@pytest.mark.asyncio
async def test_completion_preserves_reasoning_tools_and_accounting(monkeypatch):
    model = LLMModel(
        provider_type="openai",
        provider=OPENAI,
        model_name="test-model",
        input_cost_per_token=0.001,
        output_cost_per_token=0.002,
    )
    captured: dict = {}
    _serve_sse(
        monkeypatch,
        model,
        [
            {"choices": [{"delta": {"reasoning_content": "why"}}]},
            {"choices": [{"delta": {"content": "hello"}}]},
            {
                "choices": [
                    {
                        "delta": {
                            "tool_calls": [
                                {
                                    "index": 0,
                                    "id": "call-1",
                                    "function": {"name": "lookup", "arguments": '{"x":'},
                                }
                            ]
                        }
                    }
                ]
            },
            {"choices": [{"delta": {"tool_calls": [{"index": 0, "function": {"arguments": "1}"}}]}}]},
            {"choices": [], "usage": {"prompt_tokens": 10, "completion_tokens": 5}},
        ],
        captured,
    )

    response = await model.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert response.reasoning_content == "why"
    assert response.content == "hello"
    assert response.tool_calls == [
        {"id": "call-1", "type": "function", "function": {"name": "lookup", "arguments": '{"x":1}'}}
    ]
    assert response.usage is not None
    assert (response.usage.prompt_tokens, response.usage.completion_tokens) == (10, 5)
    assert response.cost == Decimal("0.02")


@pytest.mark.asyncio
async def test_an_error_status_carries_the_provider_message(monkeypatch):
    from agentarea_agents_sdk.models.llm_model import LLMProviderHTTPError

    model = LLMModel(provider_type="openai", provider=OPENAI, model_name="m", api_key="k")
    _serve_sse(
        monkeypatch,
        model,
        [],
        {},
        status=429,
        body={"error": {"message": "slow down"}},
    )

    with pytest.raises(LLMProviderHTTPError) as raised:
        await model.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))
    assert raised.value.status_code == 429
    assert raised.value.provider_message == "slow down"


def test_a_provider_with_no_address_and_no_endpoint_is_refused():
    model = LLMModel(provider_type="ollama", model_name="llama3")

    with pytest.raises(ValueError, match="no public address"):
        model._api_url("/chat/completions")


@pytest.mark.asyncio
async def test_a_reply_cut_off_at_the_output_limit_says_so(monkeypatch):
    model = LLMModel(provider_type="openai", model_name="m", endpoint_url="https://x.example/v1")
    captured: dict = {}
    _serve_sse(
        monkeypatch,
        model,
        [
            {"choices": [{"delta": {"content": "part"}}]},
            {"choices": [{"delta": {}, "finish_reason": "length"}]},
        ],
        captured,
    )

    response = await model.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))

    assert (response.content, response.finish_reason) == ("part", "length")
    assert "think" not in captured["json"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("reasoning_param", "fields"),
    [
        ("reasoning_effort", {"reasoning_effort": "low"}),
        ("reasoning", {"reasoning": {"effort": "low"}}),
    ],
)
async def test_the_reasoning_effort_is_asked_for_in_the_providers_form(
    monkeypatch, reasoning_param, fields
):
    from agentarea_agents_sdk.models.provider_profiles import ProviderProfile

    model = LLMModel(
        provider_type="x",
        model_name="m",
        endpoint_url="https://x.example/v1",
        provider=ProviderProfile.from_mapping({"reasoning_param": reasoning_param}),
    )
    captured: dict = {}
    _serve_sse(monkeypatch, model, [{"choices": [{"delta": {"content": "ok"}}]}], captured)

    await model.complete(
        LLMRequest(messages=[{"role": "user", "content": "hi"}], reasoning_effort="low")
    )

    assert {k: captured["json"][k] for k in fields} == fields
