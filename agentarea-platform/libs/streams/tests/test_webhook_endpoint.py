"""A subscriber's callback endpoint: https only, a development receiver, the challenge, outcomes."""

import base64
import json

import httpx
import pytest
from agentarea_common.utils.url_safety import OutboundPolicy
from agentarea_streams.application.webhook_endpoint import WebhookEndpoint
from agentarea_streams.domain.mcp_events import ErrorCode, EventsError, sign

SECRET = "whsec_" + base64.b64encode(b"s" * 32).decode()  # pragma: allowlist secret


def _resolve(*addresses: str):
    async def resolve(host: str, port: int) -> list[str]:
        return list(addresses)

    return resolve


def _endpoint(handler, *, policy: OutboundPolicy | None = None, resolve=None) -> WebhookEndpoint:
    return WebhookEndpoint(
        policy=policy or OutboundPolicy(),
        resolve=resolve or _resolve("8.8.8.8"),
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=lambda: 1_700_000_000,
    )


def _ok(request: httpx.Request) -> httpx.Response:
    return httpx.Response(200)


async def test_an_https_callback_is_accepted():
    await _endpoint(_ok).check("https://hooks.example/a")


@pytest.mark.parametrize(
    "url", ["ftp://hooks.example/a", "https:///nohost", "http://hooks.example/a"]
)
async def test_anything_else_is_invalid_params(url):
    with pytest.raises(EventsError) as raised:
        await _endpoint(_ok).check(url)
    assert raised.value.code == ErrorCode.INVALID_PARAMS


async def test_http_reaches_only_a_private_receiver_the_policy_admits():
    admitted = OutboundPolicy(private_allowlist=("host.docker.internal",))
    await _endpoint(_ok, policy=admitted, resolve=_resolve("192.168.65.254")).check(
        "http://host.docker.internal:8790/hook"
    )
    with pytest.raises(EventsError):
        await _endpoint(_ok, resolve=_resolve("192.168.65.254")).check(
            "http://host.docker.internal:8790/hook"
        )
    with pytest.raises(EventsError):
        await _endpoint(_ok, policy=OutboundPolicy(allow_private=True)).check(
            "http://hooks.example/a"
        )


async def test_a_post_is_signed_per_standard_webhooks():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(204)

    outcome = await _endpoint(handler).post(
        url="https://hooks.example/a",
        secret=SECRET,
        subscription="sub_1",
        message_id="evt_1",
        body={"eventId": "evt_1"},
    )
    assert outcome.error is None
    request = seen[0]
    assert request.headers["webhook-id"] == "evt_1"
    assert request.headers["webhook-timestamp"] == "1700000000"
    assert request.headers["x-mcp-subscription-id"] == "sub_1"
    assert request.headers["webhook-signature"] == sign(
        SECRET, "evt_1", 1_700_000_000, request.content
    )


@pytest.mark.parametrize(
    ("status", "error", "final"),
    [
        (500, "http_5xx", False),
        (404, "http_4xx", False),
        (410, "http_4xx", True),
        (413, "http_4xx", True),
    ],
)
async def test_a_refusal_is_reported_by_its_category_only(status, error, final):
    outcome = await _endpoint(lambda r: httpx.Response(status, text="secret internals")).post(
        url="https://hooks.example/a", secret=SECRET, subscription="s", message_id="m", body={}
    )
    assert (outcome.error, outcome.final) == (error, final)


async def test_an_unreachable_endpoint_is_a_connection_category():
    def timeout(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    def refused(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    post = {
        "url": "https://hooks.example/a",
        "secret": SECRET,
        "subscription": "s",
        "message_id": "m",
        "body": {},
    }
    assert (await _endpoint(timeout).post(**post)).error == "timeout"
    assert (await _endpoint(refused).post(**post)).error == "connection_refused"


async def test_the_challenge_passes_only_when_echoed():
    def echo(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["type"] == "verification"
        assert request.headers["webhook-id"].startswith("msg_verification_")
        return httpx.Response(200, json={"challenge": body["challenge"]})

    await _endpoint(echo).challenge(url="https://hooks.example/a", secret=SECRET, subscription="s")
    for handler, reason in (
        (lambda r: httpx.Response(200, json={"challenge": "guess"}), "challenge_failed"),
        (lambda r: httpx.Response(200, text="ok"), "challenge_failed"),
        (lambda r: httpx.Response(500), "http_5xx"),
    ):
        with pytest.raises(EventsError) as raised:
            await _endpoint(handler).challenge(
                url="https://hooks.example/a", secret=SECRET, subscription="s"
            )
        assert raised.value.code == ErrorCode.CALLBACK_ENDPOINT_ERROR
        assert raised.value.data == {"reason": reason}
