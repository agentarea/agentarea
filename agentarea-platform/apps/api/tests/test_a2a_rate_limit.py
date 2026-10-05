"""The A2A limit is per caller, not per address.

Agent-to-agent delegation reaches the A2A endpoint from the worker, so every
workspace's delegations share one source address. Keyed on that address, one
busy workspace exhausted the bucket and every other workspace's delegations
failed with 429.
"""

from collections import Counter

import pytest
from agentarea_api.api import rate_limit
from agentarea_common.auth.context import UserPrincipal
from agentarea_common.auth.dependencies import get_optional_principal
from fastapi import Depends, FastAPI, Request
from fastapi.testclient import TestClient

LIMIT = 2


class _CountingRedis:
    """Admits ``limit`` calls per key, which is all the token bucket does within a minute."""

    def __init__(self) -> None:
        self.calls: Counter[str] = Counter()

    async def eval(self, _script, _numkeys, key, limit, _ttl):
        self.calls[key] += 1
        return [1, 0] if self.calls[key] <= int(limit) else [0, 60]


def _principal(request: Request) -> UserPrincipal | None:
    key = request.headers.get("x-test-key")
    if key is None:
        return None
    return UserPrincipal(user_id="user-shared", api_key_id=key)


@pytest.fixture
def client(monkeypatch) -> TestClient:
    monkeypatch.setattr(rate_limit, "_A2A_RPC_LIMIT_PER_MINUTE", LIMIT)
    redis = _CountingRedis()
    monkeypatch.setattr(rate_limit, "_get_redis_client", lambda: redis)
    app = FastAPI()

    @app.post("/rpc", dependencies=[Depends(rate_limit.limit_a2a_rpc)])
    async def rpc() -> dict[str, str]:
        return {"ok": "yes"}

    app.dependency_overrides[get_optional_principal] = _principal
    return TestClient(app)


def test_one_key_exhausting_its_bucket_leaves_another_key_from_the_same_address(client) -> None:
    for _ in range(LIMIT):
        assert client.post("/rpc", headers={"x-test-key": "key-busy"}).status_code == 200
    assert client.post("/rpc", headers={"x-test-key": "key-busy"}).status_code == 429

    assert client.post("/rpc", headers={"x-test-key": "key-quiet"}).status_code == 200


def test_unauthenticated_callers_share_their_address_bucket(client) -> None:
    for _ in range(LIMIT):
        assert client.post("/rpc").status_code == 200
    response = client.post("/rpc")

    assert response.status_code == 429
    assert int(response.headers["Retry-After"]) >= 1
    assert client.post("/rpc", headers={"x-test-key": "key-quiet"}).status_code == 200
