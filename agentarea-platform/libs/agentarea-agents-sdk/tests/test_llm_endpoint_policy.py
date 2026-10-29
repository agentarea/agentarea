"""A member-set endpoint is held to the outbound policy on every LLM call path.

GHSA-pprc-x767-m6jg: a provider config's endpoint_url reached loopback and
in-cluster services from the platform's own pods. ``endpoint_policy`` is set
whenever the address came from a workspace member.
"""

import pytest
from agentarea_common.utils.url_safety import (
    OutboundPolicy,
    SafeOutboundTransport,
    UnsafeUrlError,
)

from agentarea_agents_sdk.models import llm_model as module
from agentarea_agents_sdk.models.llm_model import LLMModel, LLMRequest


class _Reached(Exception):
    """Raised by a stubbed transport: the call got past the guard."""


def _request() -> LLMRequest:
    return LLMRequest(messages=[{"role": "user", "content": "hi"}], max_tokens=5)


def _model(endpoint_url: str, policy: OutboundPolicy | None) -> LLMModel:
    return LLMModel(
        provider_type="openai",
        model_name="m",
        api_key="k",
        endpoint_url=endpoint_url,
        endpoint_policy=policy,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "endpoint_url",
    [
        "http://127.0.0.1:8000/v1",
        "http://10.0.0.5:8080/v1",
        "http://169.254.169.254/latest",
        "http://localhost:4434",
    ],
)
async def test_complete_refuses_a_member_endpoint_on_a_private_address(endpoint_url):
    with pytest.raises(UnsafeUrlError):
        await _model(endpoint_url, OutboundPolicy()).complete(_request())


@pytest.mark.asyncio
async def test_direct_stream_refuses_a_member_endpoint_before_connecting():
    model = _model("http://10.0.0.5:8080/v1", OutboundPolicy())

    with pytest.raises(UnsafeUrlError):
        async for _ in model.ainvoke_stream(_request()):
            pass


@pytest.mark.asyncio
async def test_direct_stream_pins_a_member_endpoint_and_not_an_operator_one():
    timeout = module.httpx.Timeout(1.0)
    async with _model("http://10.0.0.5/v1", OutboundPolicy())._http_client(timeout) as client:
        assert isinstance(client._transport, SafeOutboundTransport)
    async with _model("http://10.0.0.5/v1", None)._http_client(timeout) as client:
        assert not isinstance(client._transport, SafeOutboundTransport)


@pytest.mark.asyncio
async def test_an_allowlisted_private_endpoint_is_called():
    # Past the policy, the pinned client connects; port 9 (discard) has nothing
    # listening, so getting a connection error is getting through.
    policy = OutboundPolicy(private_allowlist=("127.0.0.1/32",))

    with pytest.raises(module.httpx.ConnectError):
        await _model("http://127.0.0.1:9/v1", policy).complete(_request())


@pytest.mark.asyncio
async def test_a_redirect_to_a_private_address_is_refused():
    class _Redirect:
        async def handle_async_request(self, request):
            return module.httpx.Response(307, headers={"location": "http://10.0.0.5/v1"})

        async def aclose(self):
            return None

    transport = SafeOutboundTransport(OutboundPolicy(), inner=lambda proxy=None: _Redirect())
    async with module.httpx.AsyncClient(transport=transport, follow_redirects=True) as client:
        with pytest.raises(UnsafeUrlError):
            await client.post("http://93.184.216.34/v1/chat/completions")


@pytest.mark.asyncio
async def test_a_refusal_does_not_name_the_resolved_address():
    with pytest.raises(UnsafeUrlError) as refused:
        await _model("http://10.0.0.5:8080/v1", OutboundPolicy()).complete(_request())
    assert "10.0.0.5" not in str(refused.value)


@pytest.mark.asyncio
async def test_an_operator_endpoint_is_called_as_given(monkeypatch):
    called: list[str] = []

    def reach(request):
        called.append(str(request.url))
        raise _Reached

    model = _model("http://10.0.0.5:8080/v1", None)
    monkeypatch.setattr(
        model,
        "_http_client",
        lambda timeout: module.httpx.AsyncClient(transport=module.httpx.MockTransport(reach)),
    )

    with pytest.raises(_Reached):
        await model.complete(_request())
    assert called == ["http://10.0.0.5:8080/v1/chat/completions"]


@pytest.mark.asyncio
async def test_streaming_with_events_refuses_a_member_endpoint_on_a_private_address():
    async def publish(content, index, final):
        return None

    with pytest.raises(UnsafeUrlError):
        await _model("http://10.0.0.5:8080/v1", OutboundPolicy()).complete_with_streaming(
            _request(), "task", "agent", "execution", publish
        )


@pytest.mark.asyncio
async def test_streaming_with_events_publishes_the_pinned_stream(monkeypatch):
    model = _model("http://93.184.216.34/v1", OutboundPolicy())

    async def pinned_stream(request):
        yield module.LLMResponse(content="Hel", role="assistant")
        yield module.LLMResponse(content="lo", role="assistant")

    monkeypatch.setattr(model, "_stream_openai_compatible", pinned_stream)
    published: list = []

    async def publish(content, index, final):
        published.append((content, index, final))

    response = await model.complete_with_streaming(
        _request(), "task", "agent", "execution", publish
    )

    assert response.content == "Hello"
    assert published == [("Hel", 0, False), ("lo", 1, False), ("", 2, True)]
