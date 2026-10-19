"""A webhook body Postgres cannot store is refused at intake, not lost later.

NaN and Infinity are not JSON numbers; jsonb refuses them, and a NUL or a lone
UTF-16 surrogate in a string. Accepted with 202, such a body reached the router
and then failed in the events view forever, so the sender never learned.
"""

from unittest.mock import AsyncMock

import pytest
from agentarea_api.api.deps.services import get_public_webhook_manager
from agentarea_api.api.rate_limit import limit_webhook
from agentarea_api.main import app
from agentarea_streams.domain.keys import MAX_REQUEST_BYTES
from httpx import ASGITransport, AsyncClient


@pytest.fixture
def manager():
    fake = AsyncMock()
    fake.handle_webhook_request.return_value = {"status_code": 202, "body": {"status": "ok"}}
    app.dependency_overrides[get_public_webhook_manager] = lambda: fake
    app.dependency_overrides[limit_webhook] = lambda: None
    yield fake
    app.dependency_overrides.pop(get_public_webhook_manager, None)
    app.dependency_overrides.pop(limit_webhook, None)


@pytest.mark.parametrize(
    ("raw", "status"),
    [
        (b'{"n": NaN}', 400),
        (b'{"n": Infinity}', 400),
        (b'{"t": "a\\u0000b"}', 422),
        (b'{"t": "\\ud800"}', 422),
        (b"{not json", 400),
    ],
)
async def test_an_unstorable_body_is_refused_before_it_is_recorded(manager, raw, status):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/hook-1", content=raw, headers={"content-type": "application/json"}
        )
    assert response.status_code == status
    manager.handle_webhook_request.assert_not_awaited()


async def test_a_storable_body_is_handed_on(manager):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/hook-1", content=b'{"n": 1.5}', headers={"content-type": "application/json"}
        )
    assert response.status_code == 202
    assert manager.handle_webhook_request.await_args.kwargs["body"] == {"n": 1.5}


async def test_a_body_past_the_request_limit_answers_413(manager):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        response = await client.post(
            "/webhooks/hook-1",
            content=b"x" * (MAX_REQUEST_BYTES + 1),
            headers={"content-type": "text/plain"},
        )
    assert response.status_code == 413
    manager.handle_webhook_request.assert_not_awaited()
