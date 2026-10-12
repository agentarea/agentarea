"""Tests for OpenFGA store/model bootstrap."""

import json

import httpx
import pytest
from agentarea_common.config.openfga import OpenFGASettings
from agentarea_common.rebac.openfga_bootstrap import bootstrap_openfga


def _settings(apply_model: bool = False, api_token: str = "") -> OpenFGASettings:
    return OpenFGASettings(
        URL="http://openfga:8080",
        STORE_ID="",
        MODEL_ID=None,
        BOOTSTRAP=True,
        APPLY_MODEL=apply_model,
        STORE_NAME="agentarea",
        API_TOKEN=api_token,
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
        if request.method == "POST" and request.url.path == "/stores/store-1/authorization-models":
            assert body == {"schema_version": "1.1", "type_definitions": []}
            return httpx.Response(201, json={"authorization_model_id": "model-2"})
        if request.method == "GET" and request.url.path == "/stores/store-1/authorization-models":
            return httpx.Response(200, json={"authorization_models": []})
        return httpx.Response(404, text="unexpected")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = _settings(apply_model=True)

    await bootstrap_openfga(settings, client=http, model_path=model_path)

    assert settings.STORE_ID == "store-1"
    assert settings.MODEL_ID == "model-2"
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

    assert settings.STORE_ID == "store-created"
    assert settings.MODEL_ID is None


@pytest.mark.asyncio
async def test_bootstrap_sends_bearer_token_when_configured():
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization"))
        if request.method == "GET" and request.url.path == "/stores":
            return httpx.Response(200, json={"stores": []})
        if request.method == "POST" and request.url.path == "/stores":
            return httpx.Response(201, json={"id": "store-created", "name": "agentarea"})
        return httpx.Response(404, text="unexpected")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = _settings(api_token="preshared-secret")  # noqa: S106

    await bootstrap_openfga(settings, client=http)

    assert seen_auth
    assert all(value == "Bearer preshared-secret" for value in seen_auth)


@pytest.mark.asyncio
async def test_bootstrap_omits_authorization_header_without_token():
    seen_auth: list[str | None] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen_auth.append(request.headers.get("authorization"))
        if request.method == "GET" and request.url.path == "/stores":
            return httpx.Response(200, json={"stores": []})
        if request.method == "POST" and request.url.path == "/stores":
            return httpx.Response(201, json={"id": "store-created", "name": "agentarea"})
        return httpx.Response(404, text="unexpected")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = _settings()

    await bootstrap_openfga(settings, client=http)

    assert seen_auth
    assert all(value is None for value in seen_auth)


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
                                "members": {"directly_related_user_types": [{"type": "User"}]}
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
        if request.method == "GET" and request.url.path == "/stores/store-1/authorization-models":
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
        if request.method == "POST" and request.url.path == "/stores/store-1/authorization-models":
            writes += 1
            return httpx.Response(201, json={"authorization_model_id": "model-new"})
        return httpx.Response(404, text="unexpected")

    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    settings = _settings(apply_model=True)

    await bootstrap_openfga(settings, client=http, model_path=model_path)

    assert settings.MODEL_ID == "model-existing"
    assert writes == 0


def test_the_model_ships_inside_the_package():
    """The process applies the model its own checks were written against.

    Deployments used to mount a copy, and one copy fell behind the image: the
    API checked ``resource#can_invoke`` against a model without it.
    """
    from agentarea_common.rebac.openfga_bootstrap import AUTHORIZATION_MODEL

    model = json.loads(AUTHORIZATION_MODEL.read_text(encoding="utf-8"))
    resource = next(t for t in model["type_definitions"] if t["type"] == "resource")
    assert {"can_read", "can_write", "can_manage", "can_invoke"} <= set(resource["relations"])


def _packaged() -> dict:
    from agentarea_common.rebac.openfga_bootstrap import AUTHORIZATION_MODEL

    return json.loads(AUTHORIZATION_MODEL.read_text(encoding="utf-8"))


def _resource(model: dict) -> dict:
    return next(t for t in model["type_definitions"] if t["type"] == "resource")


def test_the_packaged_model_is_generated_from_model_fga():
    """``fga model transform --file fga.mod`` was rerun after the last edit."""
    import re

    from agentarea_common.rebac.openfga_bootstrap import AUTHORIZATION_MODEL

    dsl = (AUTHORIZATION_MODEL.parent / "model.fga").read_text(encoding="utf-8")
    declared: dict[str, set[str]] = {}
    current = ""
    for line in dsl.splitlines():
        if match := re.match(r"type (\w+)", line):
            current = match.group(1)
            declared[current] = set()
        elif match := re.match(r"\s+define (\w+):", line):
            declared[current].add(match.group(1))
    generated = {t["type"]: set(t.get("relations") or {}) for t in _packaged()["type_definitions"]}
    assert generated == declared


def test_a_model_composed_over_the_packaged_one_is_accepted():
    """What ``fga.mod`` yields from our module plus an ``extend type`` module."""
    import copy

    from agentarea_common.rebac.openfga_bootstrap import require_extends

    base = _packaged()
    custom = copy.deepcopy(base)
    resource = _resource(custom)
    resource["relations"]["auditor"] = {"this": {}}
    resource["metadata"]["relations"]["auditor"] = {
        "directly_related_user_types": [{"type": "User"}],
        "module": "acme",
        "source_info": {"file": "acme.fga"},
    }
    resource["metadata"]["relations"]["reader"]["source_info"] = {"file": "vendor/model.fga"}
    custom["type_definitions"].append({"type": "team", "relations": {}})

    require_extends(custom, base)


def test_a_custom_model_missing_a_platform_relation_is_refused():
    """The RU outage: a copy of the model from before ``invoker`` existed."""
    import copy

    from agentarea_common.rebac.openfga_bootstrap import require_extends
    from agentarea_common.rebac.openfga_client import OpenFGAError

    base = _packaged()
    stale = copy.deepcopy(base)
    del _resource(stale)["relations"]["can_invoke"]

    with pytest.raises(OpenFGAError, match=r"resource#can_invoke is missing"):
        require_extends(stale, base)


def test_a_custom_model_redefining_a_platform_relation_is_refused():
    import copy

    from agentarea_common.rebac.openfga_bootstrap import require_extends
    from agentarea_common.rebac.openfga_client import OpenFGAError

    base = _packaged()
    widened = copy.deepcopy(base)
    _resource(widened)["relations"]["can_manage"] = {"this": {}}

    with pytest.raises(OpenFGAError, match=r"resource#can_manage is redefined"):
        require_extends(widened, base)


@pytest.mark.asyncio
async def test_a_custom_model_path_is_what_gets_applied(tmp_path):
    import copy

    base = _packaged()
    custom = copy.deepcopy(base)
    custom["type_definitions"].append({"type": "team", "relations": {}})
    custom_path = tmp_path / "custom.json"
    custom_path.write_text(json.dumps(custom), encoding="utf-8")
    written: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/stores" and request.method == "GET":
            return httpx.Response(200, json={"stores": [{"id": "store-1", "name": "agentarea"}]})
        if request.url.path.endswith("/authorization-models") and request.method == "GET":
            return httpx.Response(200, json={"authorization_models": []})
        if request.url.path.endswith("/authorization-models") and request.method == "POST":
            written.append(json.loads(request.content))
            return httpx.Response(201, json={"authorization_model_id": "model-custom"})
        return httpx.Response(404, text="unexpected")

    settings = _settings(apply_model=True)
    settings.MODEL_PATH = str(custom_path)
    await bootstrap_openfga(
        settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    assert written == [custom]
    assert settings.MODEL_ID == "model-custom"


@pytest.mark.asyncio
async def test_the_packaged_model_is_found_as_the_server_echoes_it():
    """The server returns absent collections as empty ones; that is the same model.

    Missing it wrote a fresh model on every start, so the store grew one per pod.
    """
    import copy

    echoed = copy.deepcopy(_packaged())
    echoed["id"] = "model-1"
    echoed.setdefault("conditions", {})
    for type_definition in echoed["type_definitions"]:
        type_definition.setdefault("relations", {})
        meta = type_definition.setdefault("metadata", {}) or {}
        for relation in meta.get("relations") or {}:
            meta["relations"][relation].setdefault("directly_related_user_types", [])
    writes = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal writes
        if request.url.path == "/stores" and request.method == "GET":
            return httpx.Response(200, json={"stores": [{"id": "store-1", "name": "agentarea"}]})
        if request.url.path.endswith("/authorization-models") and request.method == "GET":
            return httpx.Response(200, json={"authorization_models": [echoed]})
        if request.method == "POST":
            writes += 1
            return httpx.Response(201, json={"authorization_model_id": "model-2"})
        return httpx.Response(404, text="unexpected")

    settings = _settings(apply_model=True)
    await bootstrap_openfga(
        settings, client=httpx.AsyncClient(transport=httpx.MockTransport(handler))
    )

    assert writes == 0
    assert settings.MODEL_ID == "model-1"


def test_a_single_file_model_with_the_same_definitions_is_accepted():
    """A pre-modular (schema 1.1) copy that matches is the same model.

    Prod mounted one until its deployment was updated; it must not stop the
    first image that carries the model itself.
    """
    import copy

    from agentarea_common.rebac.openfga_bootstrap import require_extends

    base = _packaged()
    single_file = copy.deepcopy(base)
    single_file["schema_version"] = "1.1"
    for type_definition in single_file["type_definitions"]:
        for relation in ((type_definition.get("metadata") or {}).get("relations") or {}).values():
            relation.pop("module", None)
            relation.pop("source_info", None)

    require_extends(single_file, base)
