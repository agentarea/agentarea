"""MCPConnection's raw SQL, run against the real migrated schema.

Same reason as test_provider_config_sql_db: the column names in these statements
belong to models in another package, and nothing else would notice one drifting.
"""

from __future__ import annotations

import os
import uuid

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
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
ENDPOINT = "http://tool-gateway.agentarea.svc.cluster.local:8080/mcp"


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
                conn.execute(
                    text("DELETE FROM encrypted_secrets WHERE workspace_id = :ws AND secret_name = :n"),
                    {"ws": handler.PLATFORM_WORKSPACE_ID, "n": handler.mcp_secret_name_for(instance_id)},
                )
                conn.execute(
                    text("DELETE FROM mcp_server_instances WHERE id = :id"), {"id": instance_id}
                )
                conn.execute(
                    text("DELETE FROM mcp_servers WHERE id = :id"),
                    {"id": handler.platform_mcp_server_id(name)},
                )


def _spec(name: str, **overrides) -> dict:
    return {
        "name": name,
        "description": "Paid tools",
        "endpointUrl": ENDPOINT,
        "tokenSecretRef": {"name": "tool-gateway-secrets", "key": "GATEWAY_TOKEN"},
    } | overrides


def _new_name(names: list[str], label: str = "Test MCP") -> str:
    name = f"{label} {uuid.uuid4().hex[:8]}"
    names.append(name)
    return name


def _snapshot(conn, handler, name: str) -> dict:
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


def test_a_platform_mcp_connection_is_actually_written(handler, names):
    name = _new_name(names)

    server_id, instance_id = handler.sync_mcp_connection(_spec(name), TOKEN)

    assert server_id == handler.platform_mcp_server_id(name)
    assert instance_id == handler.platform_mcp_instance_id(name)
    with handler.engine.begin() as conn:
        rows = _snapshot(conn, handler, name)

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


def test_reconciling_the_same_spec_again_changes_nothing(handler, names):
    name = _new_name(names)
    handler.sync_mcp_connection(_spec(name), TOKEN)
    with handler.engine.begin() as conn:
        before = _snapshot(conn, handler, name)

    handler.sync_mcp_connection(_spec(name), TOKEN)

    with handler.engine.begin() as conn:
        after = _snapshot(conn, handler, name)
    assert after == before


def test_a_rotated_token_rewrites_the_same_secret_row(handler, names):
    name = _new_name(names)
    handler.sync_mcp_connection(_spec(name), TOKEN)
    with handler.engine.begin() as conn:
        before = _snapshot(conn, handler, name)

    handler.sync_mcp_connection(_spec(name), "rotated")

    with handler.engine.begin() as conn:
        after = _snapshot(conn, handler, name)
    assert after["secret"]["id"] == before["secret"]["id"]
    decrypted = Fernet(TEST_FERNET_KEY).decrypt(after["secret"]["encrypted_value"].encode())
    assert decrypted == b"Bearer rotated"


def test_a_changed_endpoint_resets_verification_and_an_unchanged_one_keeps_it(
    handler, names
):
    name = _new_name(names)
    _, instance_id = handler.sync_mcp_connection(_spec(name), TOKEN)
    verified = '{"schema_version": 1, "status": "succeeded", "at": "2026-10-12T00:00:00Z", "error": null}'
    with handler.engine.begin() as conn:
        conn.execute(
            text(
                "UPDATE mcp_server_instances SET verification = CAST(:v AS JSONB), "
                "tools = CAST('[{\"name\": \"search\"}]' AS JSONB) WHERE id = :id"
            ),
            {"v": verified, "id": instance_id},
        )

    handler.sync_mcp_connection(_spec(name, description="Renamed"), TOKEN)
    with handler.engine.begin() as conn:
        kept = _snapshot(conn, handler, name)
    assert kept["instance"]["verification"]["status"] == "succeeded"
    assert kept["instance"]["tools"] == [{"name": "search"}]
    assert kept["instance"]["description"] == "Renamed"
    assert kept["server"]["description"] == "Renamed"

    moved = "http://tool-gateway-v2.agentarea.svc.cluster.local:8080/mcp"
    handler.sync_mcp_connection(_spec(name, endpointUrl=moved), TOKEN)
    with handler.engine.begin() as conn:
        reset = _snapshot(conn, handler, name)
    assert reset["server"]["remote_url"] == moved
    assert reset["instance"]["verification"] == handler.NEVER_ATTEMPTED_VERIFICATION
    assert reset["instance"]["tools"] is None


def test_a_slug_taken_in_the_platform_workspace_gets_a_suffix(handler, names):
    """Two names that slug alike are two connections, not a constraint violation."""
    first = _new_name(names)
    second = first.replace(" ", "_")
    names.append(second)

    handler.sync_mcp_connection(_spec(first), TOKEN)
    handler.sync_mcp_connection(_spec(second), TOKEN)

    with handler.engine.begin() as conn:
        slugs = [
            _snapshot(conn, handler, n)["server"]["slug"] for n in (first, second)
        ]
    assert slugs[1] == f"{slugs[0]}-2"
