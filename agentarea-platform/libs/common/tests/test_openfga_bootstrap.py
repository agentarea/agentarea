"""Tests for OpenFGA store/model bootstrap."""

import json

import httpx
import pytest
from agentarea_common.config.openfga import OpenFGASettings
from agentarea_common.rebac.openfga_bootstrap import bootstrap_openfga


def _settings(model_path: str | None = None) -> OpenFGASettings:
    return OpenFGASettings(
        ACCESS_CONTROL_OPENFGA_API_URL="http://openfga:8080",
        ACCESS_CONTROL_OPENFGA_STORE_ID="",
        ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID=None,
        ACCESS_CONTROL_OPENFGA_AUTO_BOOTSTRAP=True,
        ACCESS_CONTROL_OPENFGA_AUTO_APPLY_MODEL=model_path is not None,
        ACCESS_CONTROL_OPENFGA_STORE_NAME="agentarea",
        ACCESS_CONTROL_OPENFGA_MODEL_PATH=model_path,
    )


@pytest.mark.asyncio
async def test_bootstrap_reuses_existing_store_and_writes_model(tmp_path):
    model_path = tmp_path / "authorization-model.json"
    model_path.write_text(
        json.dumps({"schema_version": "1.1", "type_definitions": []}),
        encoding="utf-8",
    )
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, request.url.path, body))
        if request.method == "GET" and request.url.path == "/stores":
            return httpx.Response(
                200,
                json={
                    "stores": [
                        {
                            "id": "store-1",
                            "name": "agentarea",
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                    ]
                },
            )
        if (
            request.method == "POST"
            and request.url.path == "/stores/store-1/authorization-models"
        ):
            assert body == {"schema_version": "1.1", "type_definitions": []}
            return httpx.Response(201, json={"authorization_model_id": "model-2"})
        if (
            request.method == "GET"
            and request.url.path == "/stores/store-1/authorization-models"
        ):
            return httpx.Response(200, json={"authorization_models": []})
        return httpx.Response(404, text="unexpected")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = _settings(str(model_path))

    await bootstrap_openfga(settings, client=http)

    assert settings.ACCESS_CONTROL_OPENFGA_STORE_ID == "store-1"
    assert settings.ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID == "model-2"
    assert [entry[:2] for entry in seen] == [
        ("GET", "/stores"),
        ("GET", "/stores/store-1/authorization-models"),
        ("POST", "/stores/store-1/authorization-models"),
    ]


@pytest.mark.asyncio
async def test_bootstrap_creates_store_when_missing_and_converges_on_listed_store():
    responses = {"list_calls": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/stores":
            responses["list_calls"] += 1
            if responses["list_calls"] == 1:
                return httpx.Response(200, json={"stores": []})
            return httpx.Response(
                200,
                json={
                    "stores": [
                        {
                            "id": "store-created",
                            "name": "agentarea",
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                    ]
                },
            )
        if request.method == "POST" and request.url.path == "/stores":
            assert json.loads(request.content) == {"name": "agentarea"}
            return httpx.Response(201, json={"id": "store-created", "name": "agentarea"})
        return httpx.Response(404, text="unexpected")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = _settings()

    await bootstrap_openfga(settings, client=http)

    assert settings.ACCESS_CONTROL_OPENFGA_STORE_ID == "store-created"
    assert settings.ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID is None


@pytest.mark.asyncio
async def test_bootstrap_reuses_matching_authorization_model(tmp_path):
    model_path = tmp_path / "authorization-model.json"
    model_path.write_text(
        json.dumps(
            {
                "schema_version": "1.1",
                "type_definitions": [
                    {
                        "type": "Workspace",
                        "relations": {"members": {"this": {}}},
                        "metadata": {
                            "relations": {
                                "members": {
                                    "directly_related_user_types": [{"type": "User"}]
                                }
                            }
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    writes = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal writes
        if request.method == "GET" and request.url.path == "/stores":
            return httpx.Response(
                200,
                json={
                    "stores": [
                        {
                            "id": "store-1",
                            "name": "agentarea",
                            "created_at": "2026-01-01T00:00:00Z",
                        }
                    ]
                },
            )
        if (
            request.method == "GET"
            and request.url.path == "/stores/store-1/authorization-models"
        ):
            return httpx.Response(
                200,
                json={
                    "authorization_models": [
                        {
                            "id": "model-existing",
                            "schema_version": "1.1",
                            "type_definitions": [
                                {
                                    "type": "Workspace",
                                    "relations": {"members": {"this": {}}},
                                    "metadata": {
                                        "relations": {
                                            "members": {
                                                "directly_related_user_types": [
                                                    {"type": "User", "condition": ""}
                                                ],
                                                "module": "",
                                                "source_info": None,
                                            }
                                        },
                                        "module": "",
                                        "source_info": None,
                                    },
                                }
                            ],
                        }
                    ]
                },
            )
        if (
            request.method == "POST"
            and request.url.path == "/stores/store-1/authorization-models"
        ):
            writes += 1
            return httpx.Response(201, json={"authorization_model_id": "model-new"})
        return httpx.Response(404, text="unexpected")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = _settings(str(model_path))

    await bootstrap_openfga(settings, client=http)

    assert settings.ACCESS_CONTROL_OPENFGA_AUTHORIZATION_MODEL_ID == "model-existing"
    assert writes == 0
