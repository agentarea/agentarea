"""MCPConnection handler: spec to rows, and the handler's failure paths."""

import json
from unittest.mock import Mock

import kopf
import pytest
from cryptography.fernet import Fernet

import handler

TOKEN = "gateway-token"  # pragma: allowlist secret
TEST_FERNET_KEY = "hEJhTL2vGZ8n1iHxzIxLh0qzRgqQPXnYYqRZcPZrQ0g="  # pragma: allowlist secret
ENDPOINT = "http://tool-gateway.agentarea.svc.cluster.local:8080/mcp"


def _spec(**overrides) -> dict:
    return {
        "name": "AgentArea Tools",
        "description": "Paid tools",
        "endpointUrl": ENDPOINT,
        "tokenSecretRef": {"name": "tool-gateway-secrets", "key": "GATEWAY_TOKEN"},
    } | overrides


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


def _sync(conn, spec, token=TOKEN):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(handler, "engine", Mock(begin=Mock(return_value=_as_context(conn))))
        return handler.sync_mcp_connection(spec, token)


def _as_context(value):
    ctx = Mock()
    ctx.__enter__ = Mock(return_value=value)
    ctx.__exit__ = Mock(return_value=False)
    return ctx


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


def test_the_token_is_filed_under_the_instance_env_var_the_runtime_resolves():
    instance_id = handler.platform_mcp_instance_id("AgentArea Tools")
    assert (
        handler.mcp_secret_name_for(instance_id)
        == f"mcp_instance_{instance_id}_Authorization"
    )


def test_a_new_connection_writes_the_server_spec(fernet_key):
    conn = _ScriptedConn()

    server_id, _ = _sync(conn, _spec())

    row = conn.params_for("INSERT INTO mcp_servers")
    assert server_id == handler.platform_mcp_server_id("AgentArea Tools")
    assert row["id"] == server_id
    assert row["name"] == "AgentArea Tools"
    assert row["slug"] == "agentarea-tools"
    assert row["desc"] == "Paid tools"
    assert row["rurl"] == ENDPOINT
    assert json.loads(row["json_spec"]) == {
        "remotes": [{"type": "streamable-http", "url": ENDPOINT}]
    }
    assert row["ws"] == handler.PLATFORM_WORKSPACE_ID


def test_a_missing_description_is_stored_empty_not_null(fernet_key):
    conn = _ScriptedConn()
    spec = _spec()
    del spec["description"]

    _sync(conn, spec)

    assert conn.params_for("INSERT INTO mcp_servers")["desc"] == ""
    assert conn.params_for("INSERT INTO mcp_server_instances")["desc"] == ""


def test_a_new_connection_writes_a_platform_managed_instance(fernet_key):
    conn = _ScriptedConn()

    server_id, instance_id = _sync(conn, _spec(transport="sse"))

    row = conn.params_for("INSERT INTO mcp_server_instances")
    assert instance_id == handler.platform_mcp_instance_id("AgentArea Tools")
    assert row["id"] == instance_id
    assert row["server_spec_id"] == server_id
    assert json.loads(row["json_spec"]) == {"env_vars": ["Authorization"]}
    assert row["ws"] == handler.PLATFORM_WORKSPACE_ID
    assert row["managed_by"] == handler.MANAGED_BY_PLATFORM
    assert json.loads(conn.params_for("INSERT INTO mcp_servers")["json_spec"]) == {
        "remotes": [{"type": "sse", "url": ENDPOINT}]
    }


def test_the_token_is_stored_encrypted_as_a_bearer_header(fernet_key):
    conn = _ScriptedConn()

    _, instance_id = _sync(conn, _spec())

    secret = conn.params_for("INSERT INTO encrypted_secrets")
    assert secret["name"] == f"mcp_instance_{instance_id}_Authorization"
    assert secret["ws"] == handler.PLATFORM_WORKSPACE_ID
    assert secret["owner_type"] == "mcp_instance"
    assert secret["owner"] == instance_id
    assert secret["val"] != f"Bearer {TOKEN}"
    assert Fernet(TEST_FERNET_KEY).decrypt(secret["val"].encode()).decode() == f"Bearer {TOKEN}"


def test_an_unchanged_token_is_not_rewritten(fernet_key):
    """Fernet output differs every call, so an unconditional upsert would rewrite
    the row on every reconcile; the same value must leave it alone."""
    stored = Fernet(TEST_FERNET_KEY).encrypt(f"Bearer {TOKEN}".encode()).decode()
    conn = _ScriptedConn({"FROM encrypted_secrets": ("55555555-5555-5555-5555-555555555555", stored)})

    _sync(conn, _spec())

    assert not conn.issued("INSERT INTO encrypted_secrets")


def test_a_rotated_token_is_rewritten(fernet_key):
    stored = Fernet(TEST_FERNET_KEY).encrypt(b"Bearer old").decode()
    conn = _ScriptedConn({"FROM encrypted_secrets": ("55555555-5555-5555-5555-555555555555", stored)})

    _sync(conn, _spec())

    assert conn.issued("INSERT INTO encrypted_secrets")


def test_an_existing_connection_is_updated_not_reinserted(fernet_key):
    conn = _ScriptedConn(
        {
            "FROM mcp_servers WHERE id": (
                ENDPOINT,
                {"remotes": [{"type": "streamable-http", "url": ENDPOINT}]},
            ),
            "FROM mcp_server_instances WHERE id": ("x",),
        }
    )

    _sync(conn, _spec())

    assert not conn.issued("INSERT INTO mcp_servers")
    assert not conn.issued("INSERT INTO mcp_server_instances")
    update = next(s for s, _ in conn.calls if s.startswith("UPDATE mcp_server_instances"))
    assert "verification" not in update, "an unchanged endpoint must keep its verification"
    assert conn.params_for("UPDATE mcp_server_instances")["ws"] == handler.PLATFORM_WORKSPACE_ID


def test_a_changed_endpoint_resets_verification_and_tools(fernet_key):
    old = "http://old-gateway.agentarea.svc.cluster.local:8080/mcp"
    conn = _ScriptedConn(
        {
            "FROM mcp_servers WHERE id": (old, {"remotes": [{"type": "streamable-http", "url": old}]}),
            "FROM mcp_server_instances WHERE id": ("x",),
        }
    )

    _sync(conn, _spec())

    sql, params = next(c for c in conn.calls if c[0].startswith("UPDATE mcp_server_instances"))
    assert "tools = NULL" in sql
    assert json.loads(params["verification"]) == handler.NEVER_ATTEMPTED_VERIFICATION


def test_a_changed_transport_resets_verification(fernet_key):
    conn = _ScriptedConn(
        {
            "FROM mcp_servers WHERE id": (ENDPOINT, {"remotes": [{"type": "sse", "url": ENDPOINT}]}),
            "FROM mcp_server_instances WHERE id": ("x",),
        }
    )

    _sync(conn, _spec())

    sql = next(s for s, _ in conn.calls if s.startswith("UPDATE mcp_server_instances"))
    assert "verification" in sql


def test_a_missing_encryption_key_refuses(monkeypatch):
    monkeypatch.setattr(handler, "ENCRYPTION_KEY", "")

    with pytest.raises(kopf.PermanentError, match="AGENTAREA_SECRET_ENCRYPTION_KEY"):
        _sync(_ScriptedConn(), _spec())


class _Patch:
    def __init__(self):
        self.status: dict = {}


def test_the_handler_records_the_synced_ids(monkeypatch):
    monkeypatch.setattr(handler, "read_secret", lambda *a, **k: TOKEN)
    monkeypatch.setattr(handler, "sync_mcp_connection", lambda spec, token: ("srv", "inst"))

    patch = _Patch()
    handler.on_mcp_connection_change(
        spec=_spec(), meta={"name": "tool-gateway"}, namespace="agentarea", patch=patch
    )

    assert patch.status["phase"] == "Synced"
    assert patch.status["mcpServerId"] == "srv"
    assert patch.status["mcpInstanceId"] == "inst"


def test_a_missing_token_secret_is_retried(monkeypatch):
    """Same as a provider's key: the resource waits for the Secret and converges."""

    def missing(*_a, **_k):
        raise RuntimeError("secrets 'tool-gateway-secrets' not found")

    monkeypatch.setattr(handler, "read_secret", missing)
    sync = Mock()
    monkeypatch.setattr(handler, "sync_mcp_connection", sync)

    patch = _Patch()
    with pytest.raises(kopf.TemporaryError):
        handler.on_mcp_connection_change(
            spec=_spec(), meta={"name": "tool-gateway"}, namespace="agentarea", patch=patch
        )

    sync.assert_not_called()
    assert patch.status["phase"] == "Error"
    assert "tool-gateway-secrets" in patch.status["message"]


def test_a_cross_namespace_token_ref_is_rejected_without_reading_it(monkeypatch):
    read_secret = Mock(side_effect=AssertionError("must not read a cross-namespace secret"))
    monkeypatch.setattr(handler, "read_secret", read_secret)

    spec = _spec(tokenSecretRef={"name": "s", "key": "k", "namespace": "other-ns"})
    patch = _Patch()
    handler.on_mcp_connection_change(
        spec=spec, meta={"name": "tool-gateway"}, namespace="agentarea", patch=patch
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
        handler.on_mcp_connection_change(
            spec=_spec(), meta={"name": "tool-gateway"}, namespace="agentarea", patch=patch
        )

    assert patch.status["phase"] == "Error"
    assert "AGENTAREA_SECRET_ENCRYPTION_KEY" in patch.status["message"]


def test_the_timer_resyncs_a_rotated_token(monkeypatch):
    monkeypatch.setattr(handler, "read_secret", lambda *a, **k: "rotated")
    sync = Mock(return_value=("srv", "inst"))
    monkeypatch.setattr(handler, "sync_mcp_connection", sync)

    patch = _Patch()
    handler.periodic_mcp_connection_resync(
        spec=_spec(), meta={"name": "tool-gateway"}, namespace="agentarea", patch=patch
    )

    assert sync.call_args.args[1] == "rotated"
    assert patch.status["phase"] == "Synced"
