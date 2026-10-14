"""PlatformConnection handler: spec to rows for both transports, and the failure paths."""

import json
from unittest.mock import Mock

import httpx
import kopf
import pytest
import yaml
from cryptography.fernet import Fernet

import handler

TOKEN = "gateway-token"  # pragma: allowlist secret
TEST_FERNET_KEY = "hEJhTL2vGZ8n1iHxzIxLh0qzRgqQPXnYYqRZcPZrQ0g="  # pragma: allowlist secret
ENDPOINT = "http://agentarea-llm-gateway.agentarea.svc.cluster.local:8080/tools/example/mcp"
GATEWAY = "http://agentarea-llm-gateway.agentarea.svc.cluster.local:8080/tools/yandex-search"
CATALOG_ID = "ru.yandex/search-api/openapi"
ITEM_ID = "66666666-6666-6666-6666-666666666666"
SPEC_URL = "https://catalog.example/yandex-search.json"

OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Search", "version": "1"},
    "components": {
        "parameters": {
            "Region": {"name": "region", "in": "query", "schema": {"type": "integer"}}
        },
        "schemas": {
            "Query": {"type": "object", "properties": {"text": {"type": "string"}}}
        },
    },
    "paths": {
        "/folders/{folder_id}/search": {
            "parameters": [
                {"name": "folder_id", "in": "path", "required": True},
                {"name": "page", "in": "query", "schema": {"type": "integer"}},
            ],
            "post": {
                "operationId": "webSearch",
                "summary": "Search the web",
                "parameters": [
                    {"$ref": "#/components/parameters/Region"},
                    {
                        "name": "page",
                        "in": "query",
                        "required": True,
                        "schema": {"type": "integer", "minimum": 0},
                    },
                ],
                "requestBody": {
                    "content": {
                        "application/json": {"schema": {"$ref": "#/components/schemas/Query"}}
                    }
                },
            },
            "get": {
                "description": "Status of the folder",
                "requestBody": {
                    "required": False,
                    "content": {"application/json": {"schema": {"type": "object"}}},
                },
            },
        }
    },
}


def _mcp_spec(**overrides) -> dict:
    return {
        "name": "AgentArea Tools",
        "description": "Paid tools",
        "transport": "mcp",
        "endpointUrl": ENDPOINT,
        "tokenSecretRef": {"name": "agentarea-tools-token", "key": "TOKEN"},
    } | overrides


def _openapi_spec(**overrides) -> dict:
    return {
        "name": "Yandex Search",
        "description": "Web search",
        "transport": "openapi",
        "endpointUrl": GATEWAY,
        "catalogId": CATALOG_ID,
        "tokenSecretRef": {"name": "agentarea-tools-token", "key": "TOKEN"},
    } | overrides


CATALOG_ROW = (ITEM_ID, {"spec_url": SPEC_URL, "connection_type": "openapi"})


class _ScriptedConn:
    """Records statements; a SELECT answers from ``rows`` by a fragment of its SQL."""

    def __init__(self, rows: dict | None = None):
        self.rows = rows or {}
        self.calls = []

    def execute(self, statement, params=None):
        sql = str(statement)
        self.calls.append((sql, params or {}))
        row = next((r for fragment, r in self.rows.items() if fragment in sql), None)
        if row is None and sql.startswith("INSERT INTO encrypted_secrets"):
            row = ("44444444-4444-4444-4444-444444444444",)

        class _Result:
            @staticmethod
            def fetchone():
                return row

        return _Result()

    def params_for(self, fragment):
        for sql, params in self.calls:
            if fragment in sql:
                return params
        raise AssertionError(f"no statement containing {fragment!r} was issued")

    def issued(self, fragment) -> bool:
        return any(fragment in sql for sql, _ in self.calls)


@pytest.fixture
def fernet_key(monkeypatch):
    monkeypatch.setattr(handler, "ENCRYPTION_KEY", TEST_FERNET_KEY)


@pytest.fixture
def served_spec(monkeypatch):
    """httpx.get answering with OPENAPI_SPEC; the list records the requested urls."""
    requested: list[str] = []

    def get(url, **_):
        requested.append(url)
        return httpx.Response(200, text=json.dumps(OPENAPI_SPEC), request=httpx.Request("GET", url))

    monkeypatch.setattr(handler.httpx, "get", get)
    return requested


def _sync(conn, spec, token=TOKEN):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(handler, "engine", Mock(begin=Mock(return_value=_as_context(conn))))
        return handler.sync_platform_connection(spec, token)


def _as_context(value):
    ctx = Mock()
    ctx.__enter__ = Mock(return_value=value)
    ctx.__exit__ = Mock(return_value=False)
    return ctx


# ─── ids and secret names ───


def test_mcp_ids_match_the_platform_copy_of_the_recipe():
    """Pinned on both sides, like the provider ids: agents and clients attach the
    instance id, so a drift here detaches every one of them without an error."""
    assert (
        handler.platform_mcp_server_id("AgentArea Tools")
        == "b9bd2429-9047-5d04-8b0a-779086f78cb6"
    )
    assert (
        handler.platform_mcp_instance_id("AgentArea Tools")
        == "2a0d7536-9583-55fb-84b3-068f76ab4701"
    )


def test_the_openapi_connection_id_is_frozen():
    """Agents and clients attach it; a drift detaches them all."""
    assert (
        handler.platform_openapi_connection_id("Yandex Search")
        == "624ee9ae-d4e4-522f-a2b5-b00ef70b021c"
    )


def test_tokens_are_filed_under_the_names_the_runtime_resolves():
    instance_id = handler.platform_mcp_instance_id("AgentArea Tools")
    assert (
        handler.mcp_secret_name_for(instance_id)
        == f"mcp_instance_{instance_id}_Authorization"
    )
    connection_id = handler.platform_openapi_connection_id("Yandex Search")
    assert (
        handler.openapi_secret_name_for(connection_id)
        == f"openapi:{connection_id}:header:Authorization"
    )


# ─── transport: mcp ───


def test_a_new_mcp_connection_writes_the_server_spec(fernet_key):
    conn = _ScriptedConn()

    instance_id, server_id = _sync(conn, _mcp_spec())

    row = conn.params_for("INSERT INTO mcp_servers")
    assert server_id == handler.platform_mcp_server_id("AgentArea Tools")
    assert instance_id == handler.platform_mcp_instance_id("AgentArea Tools")
    assert row["id"] == server_id
    assert row["name"] == "AgentArea Tools"
    assert row["slug"] == "agentarea-tools"
    assert row["desc"] == "Paid tools"
    assert row["rurl"] == ENDPOINT
    assert json.loads(row["json_spec"]) == {
        "remotes": [{"type": "streamable-http", "url": ENDPOINT}]
    }
    assert row["ws"] == handler.PLATFORM_WORKSPACE_ID
    assert not conn.issued("FROM registry_items"), "no catalogId, no catalog lookup"


def test_a_catalog_mcp_connection_carries_the_catalog_metadata(fernet_key):
    metadata = {"agentarea:payers": ["platform"], "agentarea:cost": {"per_call": "0.5"}}
    conn = _ScriptedConn(
        {"FROM registry_items": (ITEM_ID, {"raw_spec": {"name": "x", "metadata": metadata}})}
    )

    _sync(conn, _mcp_spec(catalogId="ai.example/tools", mcpTransport="sse"))

    assert conn.params_for("FROM registry_items")["ext"] == "ai.example/tools"
    assert json.loads(conn.params_for("INSERT INTO mcp_servers")["json_spec"]) == {
        "name": "ai.example/tools",
        "metadata": metadata,
        "remotes": [{"type": "sse", "url": ENDPOINT}],
    }


def test_a_missing_catalog_item_waits_for_the_catalog(fernet_key):
    conn = _ScriptedConn()

    with pytest.raises(kopf.TemporaryError, match="ai.example/tools") as exc:
        _sync(conn, _mcp_spec(catalogId="ai.example/tools"))

    assert exc.value.delay == handler.CATALOG_RETRY_DELAY
    assert not conn.issued("INSERT INTO mcp_servers")


def test_a_missing_description_is_stored_empty_not_null(fernet_key):
    conn = _ScriptedConn()
    spec = _mcp_spec()
    del spec["description"]

    _sync(conn, spec)

    assert conn.params_for("INSERT INTO mcp_servers")["desc"] == ""
    assert conn.params_for("INSERT INTO mcp_server_instances")["desc"] == ""


def test_a_new_mcp_connection_writes_a_platform_managed_instance(fernet_key):
    conn = _ScriptedConn()

    instance_id, server_id = _sync(conn, _mcp_spec())

    row = conn.params_for("INSERT INTO mcp_server_instances")
    assert row["id"] == instance_id
    assert row["server_spec_id"] == server_id
    assert json.loads(row["json_spec"]) == {"env_vars": ["Authorization"]}
    assert row["ws"] == handler.PLATFORM_WORKSPACE_ID
    assert row["managed_by"] == handler.MANAGED_BY_PLATFORM


def test_the_mcp_token_is_stored_encrypted_as_a_bearer_header(fernet_key):
    conn = _ScriptedConn()

    instance_id, _ = _sync(conn, _mcp_spec())

    secret = conn.params_for("INSERT INTO encrypted_secrets")
    assert secret["name"] == f"mcp_instance_{instance_id}_Authorization"
    assert secret["ws"] == handler.PLATFORM_WORKSPACE_ID
    assert secret["owner_type"] == "mcp_instance"
    assert secret["owner"] == instance_id
    assert Fernet(TEST_FERNET_KEY).decrypt(secret["val"].encode()).decode() == f"Bearer {TOKEN}"


def test_an_unchanged_token_is_not_rewritten(fernet_key):
    """Fernet output differs every call, so an unconditional upsert would rewrite
    the row on every reconcile; the same value must leave it alone."""
    stored = Fernet(TEST_FERNET_KEY).encrypt(f"Bearer {TOKEN}".encode()).decode()
    conn = _ScriptedConn({"FROM encrypted_secrets": ("55555555-5555-5555-5555-555555555555", stored)})

    _sync(conn, _mcp_spec())

    assert not conn.issued("INSERT INTO encrypted_secrets")


def test_a_rotated_token_is_rewritten(fernet_key):
    stored = Fernet(TEST_FERNET_KEY).encrypt(b"Bearer old").decode()
    conn = _ScriptedConn({"FROM encrypted_secrets": ("55555555-5555-5555-5555-555555555555", stored)})

    _sync(conn, _mcp_spec())

    assert conn.issued("INSERT INTO encrypted_secrets")


def test_an_existing_mcp_connection_is_updated_not_reinserted(fernet_key):
    conn = _ScriptedConn(
        {
            "FROM mcp_servers WHERE id": (
                ENDPOINT,
                {"remotes": [{"type": "streamable-http", "url": ENDPOINT}]},
            ),
            "FROM mcp_server_instances WHERE id": ("x",),
        }
    )

    _sync(conn, _mcp_spec())

    assert not conn.issued("INSERT INTO mcp_servers")
    assert not conn.issued("INSERT INTO mcp_server_instances")
    update = next(s for s, _ in conn.calls if s.startswith("UPDATE mcp_server_instances"))
    assert "verification" not in update, "an unchanged endpoint must keep its verification"
    assert "IS DISTINCT FROM" in update


def test_new_catalog_metadata_keeps_the_verification(fernet_key):
    """Only the endpoint and transport describe the server; a cost update does not."""
    remotes = [{"type": "streamable-http", "url": ENDPOINT}]
    conn = _ScriptedConn(
        {
            "FROM registry_items": (ITEM_ID, {"raw_spec": {"metadata": {"v": 2}}}),
            "FROM mcp_servers WHERE id": (ENDPOINT, {"metadata": {"v": 1}, "remotes": remotes}),
            "FROM mcp_server_instances WHERE id": ("x",),
        }
    )

    _sync(conn, _mcp_spec(catalogId="ai.example/tools"))

    update = next(s for s, _ in conn.calls if s.startswith("UPDATE mcp_server_instances"))
    assert "verification" not in update


def test_a_changed_endpoint_resets_verification_and_tools(fernet_key):
    old = "http://old-gateway.agentarea.svc.cluster.local:8080/mcp"
    conn = _ScriptedConn(
        {
            "FROM mcp_servers WHERE id": (old, {"remotes": [{"type": "streamable-http", "url": old}]}),
            "FROM mcp_server_instances WHERE id": ("x",),
        }
    )

    _sync(conn, _mcp_spec())

    sql, params = next(c for c in conn.calls if c[0].startswith("UPDATE mcp_server_instances"))
    assert "tools = NULL" in sql
    assert json.loads(params["verification"]) == handler.NEVER_ATTEMPTED_VERIFICATION


def test_a_changed_mcp_transport_resets_verification(fernet_key):
    conn = _ScriptedConn(
        {
            "FROM mcp_servers WHERE id": (ENDPOINT, {"remotes": [{"type": "sse", "url": ENDPOINT}]}),
            "FROM mcp_server_instances WHERE id": ("x",),
        }
    )

    _sync(conn, _mcp_spec())

    sql = next(s for s, _ in conn.calls if s.startswith("UPDATE mcp_server_instances"))
    assert "verification" in sql


def test_a_missing_encryption_key_refuses(monkeypatch):
    monkeypatch.setattr(handler, "ENCRYPTION_KEY", "")

    with pytest.raises(kopf.PermanentError, match="AGENTAREA_SECRET_ENCRYPTION_KEY"):
        _sync(_ScriptedConn(), _mcp_spec())


# ─── transport: openapi ───


def test_the_tool_projection_mirrors_the_core_parser():
    """Methods in the parser's order; operation params override path params in place."""
    assert handler.openapi_tools(OPENAPI_SPEC) == [
        {
            "name": "get_folders_folder_id_search",
            "description": "Status of the folder",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "folder_id": {"type": "string"},
                    "page": {"type": "integer"},
                    "body": {"type": "object"},
                },
                "required": ["folder_id"],
            },
        },
        {
            "name": "webSearch",
            "description": "Search the web",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "folder_id": {"type": "string"},
                    "page": {"type": "integer", "minimum": 0},
                    "region": {"type": "integer"},
                    "body": {"type": "object", "properties": {"text": {"type": "string"}}},
                },
                "required": ["folder_id", "page", "body"],
            },
        },
    ]


def test_a_new_openapi_connection_writes_a_platform_managed_row(fernet_key, served_spec):
    conn = _ScriptedConn({"FROM registry_items": CATALOG_ROW})

    connection_id, server_id = _sync(conn, _openapi_spec())

    assert server_id is None
    assert connection_id == handler.platform_openapi_connection_id("Yandex Search")
    assert served_spec == [SPEC_URL]
    assert conn.params_for("FROM registry_items")["ext"] == CATALOG_ID
    sql, row = next(c for c in conn.calls if c[0].startswith("INSERT INTO openapi_connections"))
    assert row["id"] == connection_id
    assert row["name"] == "Yandex Search"
    assert row["desc"] == "Web search"
    assert row["base_url"] == GATEWAY
    assert row["spec_url"] == SPEC_URL
    assert json.loads(row["spec_content"]) == OPENAPI_SPEC
    assert row["item_id"] == ITEM_ID
    assert json.loads(row["tools"]) == handler.openapi_tools(OPENAPI_SPEC)
    assert json.loads(row["headers"]) == [{"name": "Authorization", "secret": True, "value": None}]
    assert row["managed_by"] == handler.MANAGED_BY_PLATFORM
    assert row["ws"] == handler.PLATFORM_WORKSPACE_ID
    assert row["created_by"] == handler.PLATFORM_PRINCIPAL_ID
    assert "'active'" in sql
    assert not conn.issued("mcp_servers")


def test_the_openapi_token_is_stored_under_the_header_secret(fernet_key, served_spec):
    conn = _ScriptedConn({"FROM registry_items": CATALOG_ROW})

    connection_id, _ = _sync(conn, _openapi_spec())

    secret = conn.params_for("INSERT INTO encrypted_secrets")
    assert secret["name"] == f"openapi:{connection_id}:header:Authorization"
    assert secret["ws"] == handler.PLATFORM_WORKSPACE_ID
    assert secret["owner_type"] == "openapi_connection"
    assert secret["owner"] == connection_id
    assert Fernet(TEST_FERNET_KEY).decrypt(secret["val"].encode()).decode() == f"Bearer {TOKEN}"


def test_an_existing_openapi_connection_is_updated_only_when_distinct(fernet_key, served_spec):
    stored = Fernet(TEST_FERNET_KEY).encrypt(f"Bearer {TOKEN}".encode()).decode()
    conn = _ScriptedConn(
        {
            "FROM registry_items": CATALOG_ROW,
            "FROM openapi_connections WHERE id": ("x",),
            "FROM encrypted_secrets": ("55555555-5555-5555-5555-555555555555", stored),
        }
    )

    _sync(conn, _openapi_spec())

    assert not conn.issued("INSERT INTO openapi_connections")
    assert not conn.issued("INSERT INTO encrypted_secrets")
    update = next(s for s, _ in conn.calls if s.startswith("UPDATE openapi_connections"))
    assert "IS DISTINCT FROM" in update
    assert conn.params_for("UPDATE openapi_connections")["ws"] == handler.PLATFORM_WORKSPACE_ID


def test_a_yaml_spec_is_accepted(fernet_key, monkeypatch):
    url = "https://catalog.example/search.yaml"
    monkeypatch.setattr(
        handler.httpx,
        "get",
        lambda u, **_: httpx.Response(
            200, text=yaml.safe_dump(OPENAPI_SPEC), request=httpx.Request("GET", u)
        ),
    )
    conn = _ScriptedConn({"FROM registry_items": (ITEM_ID, {"spec_url": url})})

    _sync(conn, _openapi_spec())

    assert json.loads(conn.params_for("INSERT INTO openapi_connections")["spec_content"]) == OPENAPI_SPEC


def test_an_openapi_connection_without_a_catalog_item_waits(fernet_key, served_spec):
    conn = _ScriptedConn()

    with pytest.raises(kopf.TemporaryError, match=CATALOG_ID) as exc:
        _sync(conn, _openapi_spec())

    assert exc.value.delay == handler.CATALOG_RETRY_DELAY
    assert served_spec == []
    assert not conn.issued("openapi_connections")


def test_an_openapi_connection_requires_a_catalog_id(fernet_key):
    spec = _openapi_spec()
    del spec["catalogId"]

    with pytest.raises(kopf.PermanentError, match="catalogId"):
        _sync(_ScriptedConn(), spec)


def test_a_spec_fetch_failure_writes_nothing(fernet_key, monkeypatch):
    def unreachable(url, **_):
        raise httpx.ConnectError("connection refused", request=httpx.Request("GET", url))

    monkeypatch.setattr(handler.httpx, "get", unreachable)
    conn = _ScriptedConn({"FROM registry_items": CATALOG_ROW})

    with pytest.raises(httpx.ConnectError):
        _sync(conn, _openapi_spec())

    assert not conn.issued("openapi_connections")
    assert not conn.issued("encrypted_secrets")


def test_a_spec_http_error_writes_nothing(fernet_key, monkeypatch):
    monkeypatch.setattr(
        handler.httpx,
        "get",
        lambda u, **_: httpx.Response(404, text="nope", request=httpx.Request("GET", u)),
    )
    conn = _ScriptedConn({"FROM registry_items": CATALOG_ROW})

    with pytest.raises(httpx.HTTPStatusError):
        _sync(conn, _openapi_spec())

    assert not conn.issued("openapi_connections")


@pytest.mark.parametrize(
    "document",
    [["not", "an", "object"], {"swagger": "2.0", "paths": {}}, {"openapi": 3.0}],
)
def test_a_spec_that_is_not_openapi_3_is_refused(fernet_key, monkeypatch, document):
    monkeypatch.setattr(
        handler.httpx,
        "get",
        lambda u, **_: httpx.Response(200, text=json.dumps(document), request=httpx.Request("GET", u)),
    )
    conn = _ScriptedConn({"FROM registry_items": CATALOG_ROW})

    with pytest.raises(ValueError, match=SPEC_URL):
        _sync(conn, _openapi_spec())

    assert not conn.issued("openapi_connections")


def test_an_unknown_transport_is_refused():
    with pytest.raises(kopf.PermanentError, match="transport"):
        _sync(_ScriptedConn(), _mcp_spec(transport="grpc"))


# ─── handlers ───


class _Patch:
    def __init__(self):
        self.status: dict = {}


def test_the_handler_records_the_mcp_ids(monkeypatch):
    monkeypatch.setattr(handler, "read_secret", lambda *a, **k: TOKEN)
    monkeypatch.setattr(handler, "sync_mcp_connection", lambda spec, token: ("srv", "inst"))

    patch = _Patch()
    handler.on_platform_connection_change(
        spec=_mcp_spec(), meta={"name": "tools"}, namespace="agentarea", patch=patch
    )

    assert patch.status["phase"] == "Synced"
    assert patch.status["connectionId"] == "inst"
    assert patch.status["mcpServerId"] == "srv"


def test_the_handler_records_the_openapi_connection(monkeypatch):
    monkeypatch.setattr(handler, "read_secret", lambda *a, **k: TOKEN)
    monkeypatch.setattr(handler, "sync_openapi_connection", lambda spec, token: "conn")

    patch = _Patch()
    handler.on_platform_connection_change(
        spec=_openapi_spec(), meta={"name": "yandex"}, namespace="agentarea", patch=patch
    )

    assert patch.status["phase"] == "Synced"
    assert patch.status["connectionId"] == "conn"
    assert patch.status["mcpServerId"] is None


def test_a_missing_catalog_item_is_recorded_and_keeps_its_delay(monkeypatch):
    monkeypatch.setattr(handler, "read_secret", lambda *a, **k: TOKEN)

    def missing(*_a, **_k):
        raise kopf.TemporaryError("Catalog item 'x' not found", delay=handler.CATALOG_RETRY_DELAY)

    monkeypatch.setattr(handler, "sync_openapi_connection", missing)

    patch = _Patch()
    with pytest.raises(kopf.TemporaryError) as exc:
        handler.on_platform_connection_change(
            spec=_openapi_spec(), meta={"name": "yandex"}, namespace="agentarea", patch=patch
        )

    assert exc.value.delay == handler.CATALOG_RETRY_DELAY
    assert patch.status["phase"] == "Error"
    assert "Catalog item 'x'" in patch.status["message"]


def test_a_failed_spec_fetch_is_recorded_and_retried(monkeypatch):
    monkeypatch.setattr(handler, "read_secret", lambda *a, **k: TOKEN)

    def unreachable(*_a, **_k):
        raise ValueError(f"Spec at {SPEC_URL} is not OpenAPI 3.x")

    monkeypatch.setattr(handler, "sync_openapi_connection", unreachable)

    patch = _Patch()
    with pytest.raises(kopf.TemporaryError):
        handler.on_platform_connection_change(
            spec=_openapi_spec(), meta={"name": "yandex"}, namespace="agentarea", patch=patch
        )

    assert patch.status["phase"] == "Error"
    assert SPEC_URL in patch.status["message"]


def test_a_missing_token_secret_is_retried(monkeypatch):
    """Same as a provider's key: the resource waits for the Secret and converges."""

    def missing(*_a, **_k):
        raise RuntimeError("secrets 'agentarea-tools-token' not found")

    monkeypatch.setattr(handler, "read_secret", missing)
    sync = Mock()
    monkeypatch.setattr(handler, "sync_platform_connection", sync)

    patch = _Patch()
    with pytest.raises(kopf.TemporaryError):
        handler.on_platform_connection_change(
            spec=_mcp_spec(), meta={"name": "tools"}, namespace="agentarea", patch=patch
        )

    sync.assert_not_called()
    assert patch.status["phase"] == "Error"
    assert "agentarea-tools-token" in patch.status["message"]


def test_a_cross_namespace_token_ref_is_rejected_without_reading_it(monkeypatch):
    read_secret = Mock(side_effect=AssertionError("must not read a cross-namespace secret"))
    monkeypatch.setattr(handler, "read_secret", read_secret)

    spec = _openapi_spec(tokenSecretRef={"name": "s", "key": "k", "namespace": "other-ns"})
    patch = _Patch()
    handler.on_platform_connection_change(
        spec=spec, meta={"name": "yandex"}, namespace="agentarea", patch=patch
    )

    read_secret.assert_not_called()
    assert patch.status["phase"] == "Error"
    assert "tokenSecretRef.namespace 'other-ns'" in patch.status["message"]


def test_a_permanent_failure_is_written_to_the_resource_status(monkeypatch):
    monkeypatch.setattr(handler, "read_secret", lambda *a, **k: TOKEN)

    def refuse(*_a, **_k):
        raise kopf.PermanentError("AGENTAREA_SECRET_ENCRYPTION_KEY is not set")

    monkeypatch.setattr(handler, "sync_mcp_connection", refuse)

    patch = _Patch()
    with pytest.raises(kopf.PermanentError):
        handler.on_platform_connection_change(
            spec=_mcp_spec(), meta={"name": "tools"}, namespace="agentarea", patch=patch
        )

    assert patch.status["phase"] == "Error"
    assert "AGENTAREA_SECRET_ENCRYPTION_KEY" in patch.status["message"]


@pytest.mark.parametrize(
    ("spec", "target", "result"),
    [
        (_mcp_spec(), "sync_mcp_connection", ("srv", "inst")),
        (_openapi_spec(), "sync_openapi_connection", "conn"),
    ],
)
def test_the_timer_resyncs_a_rotated_token(monkeypatch, spec, target, result):
    monkeypatch.setattr(handler, "read_secret", lambda *a, **k: "rotated")
    sync = Mock(return_value=result)
    monkeypatch.setattr(handler, target, sync)

    patch = _Patch()
    handler.periodic_platform_connection_resync(
        spec=spec, meta={"name": "c"}, namespace="agentarea", patch=patch
    )

    assert sync.call_args.args[1] == "rotated"
    assert patch.status["phase"] == "Synced"
    assert patch.status["message"] == "Re-synced"
