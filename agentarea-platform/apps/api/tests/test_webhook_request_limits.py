"""The public webhook sink: request size, body reading, and handshakes answered from the entry."""

import base64
from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.deps.services import get_public_webhook_manager
from agentarea_api.api.rate_limit import limit_webhook
from agentarea_api.api.v1._webhook_intake import handshake_answer
from agentarea_api.api.v1.webhooks import MAX_REQUEST_BYTES
from agentarea_api.main import app
from agentarea_streams.domain.source_types import SourceTypeEntry
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def manager():
    fake = AsyncMock()
    fake.handle_webhook_request.return_value = {"status_code": 202, "body": {"status": "accepted"}}
    app.dependency_overrides[get_public_webhook_manager] = lambda: fake
    app.dependency_overrides[limit_webhook] = lambda: None
    yield fake
    app.dependency_overrides.pop(get_public_webhook_manager, None)
    app.dependency_overrides.pop(limit_webhook, None)


async def _post(content: bytes, content_type: str, extra: dict | None = None):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            "/webhooks/hook-1",
            content=content,
            headers={"content-type": content_type, **(extra or {})},
        )


async def test_a_request_past_the_limit_is_refused_before_it_is_handed_on(manager):
    response = await _post(
        b"{}", "application/json", {"content-length": str(MAX_REQUEST_BYTES + 1)}
    )
    assert response.status_code == 413
    manager.handle_webhook_request.assert_not_called()


async def test_the_raw_body_and_the_parsed_body_are_handed_on(manager):
    response = await _post(b'{"a": 1}', "application/json")
    assert response.status_code == 202
    kwargs = manager.handle_webhook_request.await_args.kwargs
    assert kwargs["raw_body"] == b'{"a": 1}'
    assert kwargs["body"] == {"a": 1}
    assert kwargs["method"] == "POST"


async def test_form_files_become_inline_attachments(manager):
    boundary = "b0undary"
    payload = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="subject"\r\n\r\nHello\r\n'
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="attachment1"; filename="a.txt"\r\n'
        "Content-Type: text/plain\r\n\r\nfile body\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    response = await _post(payload, f"multipart/form-data; boundary={boundary}")
    assert response.status_code == 202
    body = manager.handle_webhook_request.await_args.kwargs["body"]
    assert body["subject"] == "Hello"
    (attached,) = body["attachments"]
    assert attached["name"] == "a.txt"
    assert attached["mime"] == "text/plain"
    assert base64.b64decode(attached["content_base64"]) == b"file body"


async def test_a_body_that_is_not_json_is_refused(manager):
    response = await _post(b"{nope", "application/json")
    assert response.status_code == 400
    manager.handle_webhook_request.assert_not_called()


def test_a_handshake_is_answered_from_the_entry_and_an_event_is_not():
    entry = SourceTypeEntry.model_validate(
        {
            "slug": "chat",
            "name": "Chat",
            "delivery": "webhook",
            "verification": {"scheme": "none"},
            "handshake": [
                {
                    "when": "{body:type}",
                    "equals": "url_verification",
                    "respond": {"challenge": "{body:challenge}"},
                },
                {"when": "{body:type}", "equals": "1", "respond": {"type": 1}},
            ],
            "event": {"kind": "{body:type}"},
        }
    )
    assert handshake_answer(entry, {}, {"type": "url_verification", "challenge": "c"}) == {
        "challenge": "c"
    }
    assert handshake_answer(entry, {}, {"type": 1}) == {"type": 1}
    assert handshake_answer(entry, {}, {"type": "message"}) is None
