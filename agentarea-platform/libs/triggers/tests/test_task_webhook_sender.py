"""A task webhook delivery is signed, and waits for its secret rather than going unsigned."""

import httpx
import pytest
from agentarea_common.utils import url_safety
from agentarea_common.utils.task_webhook import sign
from agentarea_triggers.channels.adapters import make_task_webhook_sender
from agentarea_triggers.channels.exceptions import RetryableError

BODY = '{"type":"task.completed","event_id":"ev-1","total_cost":"0.01"}'


class _Reader:
    def __init__(self, secret: str | None) -> None:
        self.secret = secret
        self.names: list[str] = []

    async def get_secret(self, name: str) -> str | None:
        self.names.append(name)
        return self.secret


def _capture(monkeypatch: pytest.MonkeyPatch) -> list[httpx.Request]:
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return httpx.Response(204)

    monkeypatch.setattr(
        url_safety,
        "safe_async_client",
        lambda *, policy, **kwargs: httpx.AsyncClient(
            transport=httpx.MockTransport(handler), **kwargs
        ),
    )
    return sent


@pytest.mark.asyncio
async def test_a_signed_webhook_carries_the_signature_event_and_delivery_id(monkeypatch):
    sent = _capture(monkeypatch)
    reader = _Reader("k" * 32)

    await make_task_webhook_sender(reader)(
        {"url": "https://app.example/hook", "signed": True, "task_id": "t-1"}, BODY
    )

    (request,) = sent
    assert reader.names == ["task_webhook:t-1"]
    assert request.headers["X-AgentArea-Event"] == "task.completed"
    assert request.headers["X-AgentArea-Delivery"] == "ev-1"
    signature = request.headers["X-AgentArea-Signature"]
    timestamp = int(signature.split(",")[0].removeprefix("t="))
    assert signature == sign("k" * 32, BODY, timestamp)
    assert request.content.decode() == BODY


@pytest.mark.asyncio
async def test_a_signed_webhook_without_its_secret_yet_is_retried_not_sent(monkeypatch):
    sent = _capture(monkeypatch)

    with pytest.raises(RetryableError):
        await make_task_webhook_sender(_Reader(None))(
            {"url": "https://app.example/hook", "signed": True, "task_id": "t-1"}, BODY
        )
    assert sent == []


@pytest.mark.asyncio
async def test_an_unsigned_webhook_is_sent_without_a_signature(monkeypatch):
    sent = _capture(monkeypatch)

    await make_task_webhook_sender(_Reader(None))(
        {"url": "https://app.example/hook", "signed": False, "task_id": "t-1"}, BODY
    )

    assert "X-AgentArea-Signature" not in sent[0].headers
