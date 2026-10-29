"""The Anthropic transport speaks the Messages API and yields the OpenAI path's deltas."""

import json
from decimal import Decimal

import pytest

from agentarea_agents_sdk.models import llm_model as module
from agentarea_agents_sdk.models.llm_model import (
    LLMModel,
    LLMProviderHTTPError,
    LLMRequest,
    to_anthropic_messages,
    to_anthropic_tools,
)
from agentarea_agents_sdk.models.provider_profiles import AuthStyle, ProviderProfile, Transport

ANTHROPIC = ProviderProfile(
    base_url="https://api.anthropic.com/v1",
    transport=Transport.ANTHROPIC,
    auth=AuthStyle.API_KEY_HEADER,
)


def test_system_goes_apart_and_tool_turns_become_blocks():
    system, turns = to_anthropic_messages(
        [
            {"role": "system", "content": "be brief"},
            {"role": "user", "content": "weather in Paris?"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "toolu_1",
                        "type": "function",
                        "function": {"name": "weather", "arguments": '{"city": "Paris"}'},
                    }
                ],
            },
            {"role": "tool", "tool_call_id": "toolu_1", "content": "18C"},
            {"role": "user", "content": "and tomorrow?"},
        ]
    )

    assert system == "be brief"
    assert turns == [
        {"role": "user", "content": [{"type": "text", "text": "weather in Paris?"}]},
        {
            "role": "assistant",
            "content": [
                {"type": "tool_use", "id": "toolu_1", "name": "weather", "input": {"city": "Paris"}}
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "toolu_1", "content": "18C"},
                {"type": "text", "text": "and tomorrow?"},
            ],
        },
    ]


def test_an_image_part_becomes_an_image_block():
    _, turns = to_anthropic_messages(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "what is this?"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,iVBOR"}},
                    {"type": "image_url", "image_url": {"url": "https://example.com/a.jpg"}},
                ],
            }
        ]
    )

    assert turns[0]["content"][1:] == [
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "iVBOR"}},
        {"type": "image", "source": {"type": "url", "url": "https://example.com/a.jpg"}},
    ]


def test_function_tools_become_input_schemas():
    tools = to_anthropic_tools(
        [
            {
                "type": "function",
                "function": {
                    "name": "weather",
                    "description": "Current weather",
                    "parameters": {"type": "object", "properties": {"city": {"type": "string"}}},
                },
            }
        ]
    )

    assert tools == [
        {
            "name": "weather",
            "description": "Current weather",
            "input_schema": {"type": "object", "properties": {"city": {"type": "string"}}},
        }
    ]


def _serve(monkeypatch, model, events, captured, status=200, body=None):
    def handle(request):
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["json"] = json.loads(request.content)
        if status >= 400:
            return module.httpx.Response(status, json=body or {})
        text = "".join(
            f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events
        )
        return module.httpx.Response(200, text=text)

    monkeypatch.setattr(
        model,
        "_http_client",
        lambda timeout: module.httpx.AsyncClient(transport=module.httpx.MockTransport(handle)),
    )


def _claude() -> LLMModel:
    return LLMModel(
        provider_type="anthropic",
        provider=ANTHROPIC,
        model_name="claude-sonnet-4-5",
        api_key="sk-ant",  # pragma: allowlist secret
        input_cost_per_token=Decimal("0.000003"),
        output_cost_per_token=Decimal("0.000015"),
        cached_input_cost_per_token=Decimal("0.0000003"),
    )


STREAM = [
    {
        "type": "message_start",
        "message": {
            "usage": {"input_tokens": 100, "cache_read_input_tokens": 900, "output_tokens": 1}
        },
    },
    {"type": "content_block_start", "index": 0, "content_block": {"type": "thinking"}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "thinking_delta", "thinking": "hm"}},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Let me "}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "check."}},
    {
        "type": "content_block_start",
        "index": 2,
        "content_block": {"type": "tool_use", "id": "toolu_1", "name": "weather", "input": {}},
    },
    {
        "type": "content_block_delta",
        "index": 2,
        "delta": {"type": "input_json_delta", "partial_json": '{"city": '},
    },
    {
        "type": "content_block_delta",
        "index": 2,
        "delta": {"type": "input_json_delta", "partial_json": '"Paris"}'},
    },
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 50}},
    {"type": "message_stop"},
]


@pytest.mark.asyncio
async def test_a_streamed_answer_keeps_text_thinking_tools_and_cost(monkeypatch):
    model = _claude()
    captured: dict = {}
    _serve(monkeypatch, model, STREAM, captured)

    response = await model.complete(
        LLMRequest(
            messages=[{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}],
            tools=[{"type": "function", "function": {"name": "weather", "parameters": {}}}],
        )
    )

    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["json"]["system"] == "be brief"
    assert captured["json"]["max_tokens"] == module.ANTHROPIC_DEFAULT_MAX_TOKENS
    assert captured["json"]["tool_choice"] == {"type": "auto"}
    assert response.content == "Let me check."
    assert response.reasoning_content == "hm"
    assert response.tool_calls == [
        {
            "id": "toolu_1",
            "type": "function",
            "function": {"name": "weather", "arguments": '{"city": "Paris"}'},
        }
    ]
    assert response.usage is not None
    assert (response.usage.prompt_tokens, response.usage.cached_prompt_tokens) == (1000, 900)
    assert response.usage.completion_tokens == 50
    assert response.cost == Decimal("0.000003") * 100 + Decimal("0.0000003") * 900 + Decimal(
        "0.000015"
    ) * 50


@pytest.mark.asyncio
async def test_an_error_event_inside_the_stream_raises_with_its_status(monkeypatch):
    model = _claude()
    _serve(
        monkeypatch,
        model,
        [
            {"type": "message_start", "message": {"usage": {"input_tokens": 1}}},
            {"type": "error", "error": {"type": "overloaded_error", "message": "Overloaded"}},
        ],
        {},
    )

    with pytest.raises(LLMProviderHTTPError) as raised:
        await model.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))
    assert (raised.value.status_code, raised.value.provider_message) == (529, "Overloaded")


@pytest.mark.asyncio
async def test_an_error_status_carries_the_provider_message(monkeypatch):
    model = _claude()
    _serve(
        monkeypatch,
        model,
        [],
        {},
        status=400,
        body={"type": "error", "error": {"type": "invalid_request_error", "message": "prompt is too long"}},
    )

    with pytest.raises(LLMProviderHTTPError) as raised:
        await model.complete(LLMRequest(messages=[{"role": "user", "content": "hi"}]))
    assert (raised.value.status_code, raised.value.provider_message) == (400, "prompt is too long")
