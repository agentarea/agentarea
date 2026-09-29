"""U+0000 cannot be stored by PostgreSQL, so it is refused before any handler binds it."""

import pytest
from agentarea_api.api.nul_character_middleware import NulCharacterMiddleware
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel


class _Body(BaseModel):
    name: str
    spec: dict = {}


def _client() -> TestClient:
    app = FastAPI()
    app.add_middleware(NulCharacterMiddleware)

    @app.post("/things")
    async def create(body: _Body) -> dict:
        return {"name": body.name}

    @app.get("/things/{thing_id}")
    async def get(thing_id: str, q: str = "") -> dict:
        return {"id": thing_id, "q": q}

    return TestClient(app)


@pytest.mark.parametrize(
    "body",
    [
        {"name": "a\u0000b"},
        {"name": "ok", "spec": {"nested": ["x", {"deep": "\u0000"}]}},
        {"name": "ok", "spec": {"key\u0000": 1}},
    ],
    ids=["field", "nested-value", "key"],
)
def test_a_json_string_holding_nul_is_refused(body):
    response = _client().post("/things", json=body)

    assert response.status_code == 422
    assert response.json()["code"] == "nul_character"


@pytest.mark.parametrize("url", ["/things/a%00b", "/things/x?q=a%00b"], ids=["path", "query"])
def test_a_url_holding_nul_is_refused(url):
    assert _client().get(url).status_code == 422


def test_an_escaped_backslash_is_not_mistaken_for_nul():
    response = _client().post("/things", json={"name": "\\u0000"})

    assert response.status_code == 200
    assert response.json() == {"name": "\\u0000"}


def test_malformed_json_is_left_to_request_validation():
    response = _client().post(
        "/things", content=b"{not json", headers={"content-type": "application/json"}
    )

    assert response.status_code == 422
    assert "code" not in response.json()
