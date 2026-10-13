"""PlatformConnection's raw SQL, run against the real migrated schema.

Same reason as test_provider_config_sql_db: the column names in these statements
belong to models in another package, and nothing else would notice one drifting.
"""

from __future__ import annotations

import json
import os
import uuid

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
import httpx  # noqa: E402
import kopf  # noqa: E402
from cryptography.fernet import Fernet  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

DSN = os.environ.get("OPERATOR_TEST_DATABASE_URL", "")

if not DSN and os.environ.get("OPERATOR_REQUIRE_DB") == "1":
    raise RuntimeError(
        "OPERATOR_REQUIRE_DB=1 but OPERATOR_TEST_DATABASE_URL is unset: the schema "
        "checks would have been skipped silently."
    )

pytestmark = pytest.mark.skipif(not DSN, reason="OPERATOR_TEST_DATABASE_URL is not set")

TEST_FERNET_KEY = "hEJhTL2vGZ8n1iHxzIxLh0qzRgqQPXnYYqRZcPZrQ0g="  # pragma: allowlist secret
TOKEN = "gateway-token"  # pragma: allowlist secret
ENDPOINT = "http://agentarea-llm-gateway.agentarea.svc.cluster.local:8080/tools/example/mcp"
GATEWAY = "http://agentarea-llm-gateway.agentarea.svc.cluster.local:8080/tools/yandex-search"
SPEC_URL = "https://catalog.example/yandex-search.json"
METADATA = {"agentarea:payers": ["platform"], "agentarea:cost": {"per_call": "0.732"}}

OPENAPI_SPEC = {
    "openapi": "3.0.3",
    "info": {"title": "Search", "version": "1"},
    "paths": {
        "/search": {
            "post": {
                "operationId": "webSearch",
                "summary": "Search the web",
                "parameters": [{"name": "region", "in": "query", "schema": {"type": "integer"}}],
                "requestBody": {
                    "content": {"application/json": {"schema": {"type": "object"}}}
                },
            }
        }
    },
}


@pytest.fixture
def handler(monkeypatch):
    import handler as module

    engine = create_engine(DSN, pool_pre_ping=True)
    # The column the core migration adds; a no-op once that migration has run.
    with engine.begin() as conn:
        conn.execute(
            text(
                "ALTER TABLE mcp_server_instances "
                "ADD COLUMN IF NOT EXISTS managed_by varchar(32)"
            )
        )
    monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(module, "ENCRYPTION_KEY", TEST_FERNET_KEY)
    monkeypatch.setattr(
        module.httpx,
        "get",
        lambda url, **_: httpx.Response(
            200, text=json.dumps(OPENAPI_SPEC), request=httpx.Request("GET", url)
        ),
    )
    try:
        yield module
    finally:
        engine.dispose()


@pytest.fixture
def names(handler):
    """Connection names used by a test, with their rows removed afterwards."""
    used: list[str] = []
    try:
        yield used
    finally:
        with handler.engine.begin() as conn:
            for name in used:
                instance_id = handler.platform_mcp_instance_id(name)
                connection_id = handler.platform_openapi_connection_id(name)
                conn.execute(
                    text(
                        "DELETE FROM encrypted_secrets WHERE workspace_id = :ws "
                        "AND secret_name IN (:mcp, :openapi)"
                    ),
                    {
                        "ws": handler.PLATFORM_WORKSPACE_ID,
                        "mcp": handler.mcp_secret_name_for(instance_id),
                        "openapi": handler.openapi_secret_name_for(connection_id),
                    },
                )
                conn.execute(
                    text("DELETE FROM mcp_server_instances WHERE id = :id"), {"id": instance_id}
                )
                conn.execute(
                    text("DELETE FROM mcp_servers WHERE id = :id"),
                    {"id": handler.platform_mcp_server_id(name)},
                )
                conn.execute(
                    text("DELETE FROM openapi_connections WHERE id = :id"),
                    {"id": connection_id},
                )


@pytest.fixture
def catalog(handler):
    """Adds a registry item under a fresh external id; the registry is dropped afterwards."""
    registry_ids: list[str] = []

    def add(spec: dict, *, active: bool = True, priority: int = 100) -> tuple[str, str]:
        registry_id = str(uuid.uuid4())
        item_id = str(uuid.uuid4())
        external_id = f"test.example/{uuid.uuid4().hex[:8]}/openapi"
        with handler.engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO registries (id, name, registry_type, source_type, "
                    "source_url, is_active) VALUES (:id, :name, 'mcp_servers', 'url', "
                    "'https://catalog.example', :active)"
                ),
                {"id": registry_id, "name": f"test-{registry_id}", "active": active},
            )
            conn.execute(
                text(
                    "INSERT INTO registry_items (id, registry_id, external_id, name, spec, "
                    "registry_type, registry_priority, registry_active) "
                    "VALUES (:id, :rid, :ext, 'Test item', CAST(:spec AS JSONB), "
                    "'mcp_servers', :priority, :active)"
                ),
                {
                    "id": item_id,
                    "rid": registry_id,
                    "ext": external_id,
                    "spec": json.dumps(spec),
                    "priority": priority,
                    "active": active,
                },
            )
        registry_ids.append(registry_id)
        return external_id, item_id

    try:
        yield add
    finally:
        with handler.engine.begin() as conn:
            for registry_id in registry_ids:
                conn.execute(text("DELETE FROM registries WHERE id = :id"), {"id": registry_id})


def _mcp_spec(name: str, **overrides) -> dict:
    return {
        "name": name,
        "description": "Paid tools",
        "transport": "mcp",
        "endpointUrl": ENDPOINT,
        "tokenSecretRef": {"name": "agentarea-tools-token", "key": "TOKEN"},
    } | overrides


def _openapi_spec(name: str, catalog_id: str, **overrides) -> dict:
    return {
        "name": name,
        "description": "Web search",
        "transport": "openapi",
        "endpointUrl": GATEWAY,
        "catalogId": catalog_id,
        "tokenSecretRef": {"name": "agentarea-tools-token", "key": "TOKEN"},
    } | overrides


def _new_name(names: list[str], label: str = "Test Conn") -> str:
    name = f"{label} {uuid.uuid4().hex[:8]}"
    names.append(name)
    return name


def _mcp_snapshot(conn, handler, name: str) -> dict:
    instance_id = handler.platform_mcp_instance_id(name)
    server = conn.execute(
        text("SELECT * FROM mcp_servers WHERE id = :id"),
        {"id": handler.platform_mcp_server_id(name)},
    ).mappings().one()
    instance = conn.execute(
        text("SELECT * FROM mcp_server_instances WHERE id = :id"), {"id": instance_id}
    ).mappings().one()
    secret = conn.execute(
        text("SELECT * FROM encrypted_secrets WHERE workspace_id = :ws AND secret_name = :n"),
        {"ws": handler.PLATFORM_WORKSPACE_ID, "n": handler.mcp_secret_name_for(instance_id)},
    ).mappings().one()
    return {"server": dict(server), "instance": dict(instance), "secret": dict(secret)}


def _openapi_snapshot(conn, handler, name: str) -> dict:
    connection_id = handler.platform_openapi_connection_id(name)
    connection = conn.execute(
        text("SELECT * FROM openapi_connections WHERE id = :id"), {"id": connection_id}
    ).mappings().one()
    secret = conn.execute(
        text("SELECT * FROM encrypted_secrets WHERE workspace_id = :ws AND secret_name = :n"),
        {"ws": handler.PLATFORM_WORKSPACE_ID, "n": handler.openapi_secret_name_for(connection_id)},
    ).mappings().one()
    return {"connection": dict(connection), "secret": dict(secret)}


# ─── transport: mcp ───


def test_a_platform_mcp_connection_is_actually_written(handler, names):
    name = _new_name(names)

    instance_id, server_id = handler.sync_platform_connection(_mcp_spec(name), TOKEN)

    assert server_id == handler.platform_mcp_server_id(name)
    assert instance_id == handler.platform_mcp_instance_id(name)
    with handler.engine.begin() as conn:
        rows = _mcp_snapshot(conn, handler, name)

    server = rows["server"]
    assert server["name"] == name
    assert server["slug"] == name.lower().replace(" ", "-")
    assert server["description"] == "Paid tools"
    assert server["version"] == "1.0.0"
    assert server["tags"] == []
    assert server["status"] == "active"
    assert server["is_public"] is False
    assert server["env_schema"] == []
    assert server["remote_url"] == ENDPOINT
    assert server["json_spec"] == {"remotes": [{"type": "streamable-http", "url": ENDPOINT}]}
    assert server["registry_item_id"] is None
    assert server["workspace_id"] == "platform"
    assert server["created_by"] == "platform"

    instance = rows["instance"]
    assert instance["server_spec_id"] == server_id
    assert instance["name"] == name
    assert instance["transport"] == "url"
    assert instance["json_spec"] == {"env_vars": ["Authorization"]}
    assert instance["network_scope"] == "private"
    assert instance["managed_by"] == "platform"
    assert instance["workspace_id"] == "platform"
    assert instance["verification"] == handler.NEVER_ATTEMPTED_VERIFICATION
    assert instance["tools"] is None

    secret = rows["secret"]
    assert secret["owner_type"] == "mcp_instance"
    assert secret["owner_id"] == instance_id
    assert secret["created_by"] == "platform"
    decrypted = Fernet(TEST_FERNET_KEY).decrypt(secret["encrypted_value"].encode()).decode()
    assert decrypted == f"Bearer {TOKEN}"


def test_a_catalog_mcp_connection_reads_the_active_item(handler, names, catalog):
    name = _new_name(names)
    catalog_id, _ = catalog({"raw_spec": {"name": "x", "metadata": METADATA}})

    handler.sync_platform_connection(_mcp_spec(name, catalogId=catalog_id), TOKEN)

    with handler.engine.begin() as conn:
        server = _mcp_snapshot(conn, handler, name)["server"]
    assert server["json_spec"] == {
        "name": catalog_id,
        "metadata": METADATA,
        "remotes": [{"type": "streamable-http", "url": ENDPOINT}],
    }


def test_reconciling_the_same_mcp_spec_again_changes_nothing(handler, names, catalog):
    name = _new_name(names)
    catalog_id, _ = catalog({"raw_spec": {"metadata": METADATA}})
    spec = _mcp_spec(name, catalogId=catalog_id)
    handler.sync_platform_connection(spec, TOKEN)
    with handler.engine.begin() as conn:
        before = _mcp_snapshot(conn, handler, name)

    handler.sync_platform_connection(spec, TOKEN)

    with handler.engine.begin() as conn:
        after = _mcp_snapshot(conn, handler, name)
    assert after == before


def test_a_rotated_token_rewrites_the_same_secret_row(handler, names):
    name = _new_name(names)
    handler.sync_platform_connection(_mcp_spec(name), TOKEN)
    with handler.engine.begin() as conn:
        before = _mcp_snapshot(conn, handler, name)

    handler.sync_platform_connection(_mcp_spec(name), "rotated")

    with handler.engine.begin() as conn:
        after = _mcp_snapshot(conn, handler, name)
    assert after["secret"]["id"] == before["secret"]["id"]
    decrypted = Fernet(TEST_FERNET_KEY).decrypt(after["secret"]["encrypted_value"].encode())
    assert decrypted == b"Bearer rotated"


def test_a_changed_endpoint_resets_verification_and_an_unchanged_one_keeps_it(
    handler, names
):
    name = _new_name(names)
    instance_id, _ = handler.sync_platform_connection(_mcp_spec(name), TOKEN)
    verified = '{"schema_version": 1, "status": "succeeded", "at": "2026-10-12T00:00:00Z", "error": null}'
    with handler.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE mcp_server_instances SET verification = CAST(:v AS JSONB), "
                "tools = CAST('[{\"name\": \"search\"}]' AS JSONB) WHERE id = :id"
            ),
            {"v": verified, "id": instance_id},
        )

    handler.sync_platform_connection(_mcp_spec(name, description="Renamed"), TOKEN)
    with handler.engine.begin() as conn:
        kept = _mcp_snapshot(conn, handler, name)
    assert kept["instance"]["verification"]["status"] == "succeeded"
    assert kept["instance"]["tools"] == [{"name": "search"}]
    assert kept["instance"]["description"] == "Renamed"
    assert kept["server"]["description"] == "Renamed"

    moved = "http://agentarea-llm-gateway-v2.agentarea.svc.cluster.local:8080/tools/example/mcp"
    handler.sync_platform_connection(_mcp_spec(name, endpointUrl=moved), TOKEN)
    with handler.engine.begin() as conn:
        reset = _mcp_snapshot(conn, handler, name)
    assert reset["server"]["remote_url"] == moved
    assert reset["instance"]["verification"] == handler.NEVER_ATTEMPTED_VERIFICATION
    assert reset["instance"]["tools"] is None


def test_a_slug_taken_in_the_platform_workspace_gets_a_suffix(handler, names):
    """Two names that slug alike are two connections, not a constraint violation."""
    first = _new_name(names)
    second = first.replace(" ", "_")
    names.append(second)

    handler.sync_platform_connection(_mcp_spec(first), TOKEN)
    handler.sync_platform_connection(_mcp_spec(second), TOKEN)

    with handler.engine.begin() as conn:
        slugs = [
            _mcp_snapshot(conn, handler, n)["server"]["slug"] for n in (first, second)
        ]
    assert slugs[1] == f"{slugs[0]}-2"


# ─── transport: openapi ───


def test_a_platform_openapi_connection_is_actually_written(handler, names, catalog):
    name = _new_name(names)
    catalog_id, item_id = catalog({"spec_url": SPEC_URL, "connection_type": "openapi"})

    connection_id, server_id = handler.sync_platform_connection(
        _openapi_spec(name, catalog_id), TOKEN
    )

    assert server_id is None
    assert connection_id == handler.platform_openapi_connection_id(name)
    with handler.engine.begin() as conn:
        rows = _openapi_snapshot(conn, handler, name)

    connection = rows["connection"]
    assert str(connection["id"]) == connection_id
    assert connection["workspace_id"] == "platform"
    assert connection["created_by"] == "platform"
    assert connection["name"] == name
    assert connection["description"] == "Web search"
    assert connection["base_url"] == GATEWAY
    assert connection["spec_url"] == SPEC_URL
    assert connection["spec_content"] == OPENAPI_SPEC
    assert str(connection["registry_item_id"]) == item_id
    assert connection["available_tools"] == [
        {
            "name": "webSearch",
            "description": "Search the web",
            "inputSchema": {
                "type": "object",
                "properties": {"region": {"type": "integer"}, "body": {"type": "object"}},
                "required": ["body"],
            },
        }
    ]
    assert connection["custom_headers"] == [
        {"name": "Authorization", "secret": True, "value": None}
    ]
    assert connection["allowed_auth_origins"] is None
    assert connection["status"] == "active"
    assert connection["managed_by"] == "platform"
    assert connection["auth_config_id"] is None

    secret = rows["secret"]
    assert secret["owner_type"] == "openapi_connection"
    assert secret["owner_id"] == connection_id
    assert secret["created_by"] == "platform"
    decrypted = Fernet(TEST_FERNET_KEY).decrypt(secret["encrypted_value"].encode()).decode()
    assert decrypted == f"Bearer {TOKEN}"


def test_reconciling_the_same_openapi_spec_again_changes_nothing(handler, names, catalog):
    name = _new_name(names)
    catalog_id, _ = catalog({"spec_url": SPEC_URL})
    handler.sync_platform_connection(_openapi_spec(name, catalog_id), TOKEN)
    with handler.engine.begin() as conn:
        before = _openapi_snapshot(conn, handler, name)

    handler.sync_platform_connection(_openapi_spec(name, catalog_id), TOKEN)

    with handler.engine.begin() as conn:
        after = _openapi_snapshot(conn, handler, name)
    assert after == before


def test_a_changed_openapi_spec_updates_the_row_in_place(handler, names, catalog):
    name = _new_name(names)
    catalog_id, _ = catalog({"spec_url": SPEC_URL})
    handler.sync_platform_connection(_openapi_spec(name, catalog_id), TOKEN)

    moved = GATEWAY + "-v2"
    handler.sync_platform_connection(
        _openapi_spec(name, catalog_id, endpointUrl=moved, description="Renamed"), "rotated"
    )

    with handler.engine.begin() as conn:
        rows = _openapi_snapshot(conn, handler, name)
        count = conn.execute(
            text("SELECT count(*) FROM openapi_connections WHERE id = :id"),
            {"id": handler.platform_openapi_connection_id(name)},
        ).scalar_one()
    assert count == 1
    assert rows["connection"]["base_url"] == moved
    assert rows["connection"]["description"] == "Renamed"
    decrypted = Fernet(TEST_FERNET_KEY).decrypt(rows["secret"]["encrypted_value"].encode())
    assert decrypted == b"Bearer rotated"


def test_an_inactive_catalog_item_is_not_found(handler, names, catalog):
    name = _new_name(names)
    catalog_id, _ = catalog({"spec_url": SPEC_URL}, active=False)

    with pytest.raises(kopf.TemporaryError, match=catalog_id):
        handler.sync_platform_connection(_openapi_spec(name, catalog_id), TOKEN)

    with handler.engine.begin() as conn:
        assert (
            conn.execute(
                text("SELECT 1 FROM openapi_connections WHERE id = :id"),
                {"id": handler.platform_openapi_connection_id(name)},
            ).fetchone()
            is None
        )
