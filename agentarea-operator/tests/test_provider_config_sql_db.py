"""The operator's raw SQL, run against the real migrated schema.

Everything this process writes is hand-written SQL against tables whose models
live in another package, so nothing type-checks the column names and the unit
tests next to this file mock the connection away. That gap shipped an INSERT
naming a `source` column on provider_configs that no schema has ever had: it
could not fail in CI, and in production it did not fail visibly either, because
the operator was already failing one statement earlier on table permissions.
The rows simply never appeared and the platform offered no models.

These tests need the migrated database that only the migrations-gate job has,
which is why they live behind a DSN rather than in the unit-test job.
"""

from __future__ import annotations

import os
import uuid

import pytest

sqlalchemy = pytest.importorskip("sqlalchemy")
from sqlalchemy import create_engine, text  # noqa: E402

DSN = os.environ.get("OPERATOR_TEST_DATABASE_URL", "")

# A DSN that never reaches the test prints "skipped" — which reads exactly like
# a pass in a log nobody opens. CI sets this so the absence of the database is a
# failure there while the suite still runs locally without one.
if not DSN and os.environ.get("OPERATOR_REQUIRE_DB") == "1":
    raise RuntimeError(
        "OPERATOR_REQUIRE_DB=1 but OPERATOR_TEST_DATABASE_URL is unset: the schema "
        "checks would have been skipped silently."
    )

pytestmark = pytest.mark.skipif(not DSN, reason="OPERATOR_TEST_DATABASE_URL is not set")

# Fernet needs a real key to encrypt with; it never leaves this process.
TEST_FERNET_KEY = "hEJhTL2vGZ8n1iHxzIxLh0qzRgqQPXnYYqRZcPZrQ0g="  # pragma: allowlist secret

# Named here rather than written inline, so the allowlist pragma the secret scan
# needs sits on one line instead of every call site — the same shape as API_KEY in
# test_handler.py.
GATEWAY_TOKEN = "gateway-token"  # pragma: allowlist secret
ROTATED_TOKEN = "rotated-token"  # pragma: allowlist secret


@pytest.fixture
def handler(monkeypatch):
    """The module, pointed at the test database.

    It builds its engine and reads the encryption key at import time, so both are
    replaced on the module object rather than through the environment.
    """
    import handler as module

    engine = create_engine(DSN, pool_pre_ping=True)
    monkeypatch.setattr(module, "engine", engine)
    monkeypatch.setattr(module, "ENCRYPTION_KEY", TEST_FERNET_KEY)
    try:
        yield module
    finally:
        engine.dispose()


@pytest.fixture
def provider_spec():
    """A catalog entry to hang the configuration off, removed afterwards.

    The key is unique per run: provider_specs.provider_key is unique across the
    whole table, so a fixed one turns a leftover row from a failed run into a
    failure in every run after it.
    """
    engine = create_engine(DSN)
    spec_id = uuid.uuid4()
    provider_key = f"test-operator-{uuid.uuid4().hex[:8]}"
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO provider_specs (id, provider_key, name, provider_type, "
                "is_builtin, requires_api_key, workspace_id, created_by, created_at, "
                "updated_at) VALUES (:id, :key, 'Test Provider', 'openai', false, true, "
                "'platform', 'test', now(), now())"
            ),
            {"id": spec_id, "key": provider_key},
        )
    try:
        yield provider_key
    finally:
        with engine.begin() as conn:
            # provider_configs and model_specs cascade from the spec; the secret
            # does not, and its RESTRICT foreign key means it has to go last.
            secret_ids = conn.execute(
                text(
                    "SELECT api_key_secret_id FROM provider_configs "
                    "WHERE provider_spec_id = :id AND api_key_secret_id IS NOT NULL"
                ),
                {"id": spec_id},
            ).fetchall()
            conn.execute(text("DELETE FROM provider_specs WHERE id = :id"), {"id": spec_id})
            for (secret_id,) in secret_ids:
                conn.execute(
                    text("DELETE FROM encrypted_secrets WHERE id = :id"), {"id": secret_id}
                )
        engine.dispose()


def _spec(provider_key: str) -> dict:
    return {
        "providerKey": provider_key,
        "name": "Test Provider Config",
        "endpointUrl": "http://gateway.example.svc.cluster.local:8080/v1",
        "isPublic": True,
        "models": [
            {
                "modelName": "test-model",
                "displayName": "Test Model",
                "contextWindow": 1024,
                "inputCostPerToken": 1.0e-6,
                "outputCostPerToken": 2.0e-6,
            }
        ],
    }


def test_a_platform_provider_config_is_actually_written(handler, provider_spec):
    """The whole write path, end to end, against real tables.

    This is the test the `source` column would have failed on. It asserts the
    rows exist rather than that the call returned, because the operator reported
    success for months while writing nothing.
    """
    config_id, model_count = handler.sync_provider_config(
        _spec(provider_spec), api_key=GATEWAY_TOKEN, cr_name="test-cr"
    )

    assert model_count == 1
    assert config_id == handler.platform_config_id(provider_spec)

    with handler.engine.begin() as conn:
        row = conn.execute(
            text(
                "SELECT name, api_key, api_key_secret_id, endpoint_url, managed_by, "
                "is_active, is_public, workspace_id FROM provider_configs WHERE id = :id"
            ),
            {"id": config_id},
        ).fetchone()
        assert row is not None, "sync reported success and wrote no configuration"
        assert row.name == "Test Provider Config"
        # The NAME of a secret, never the key itself.
        assert row.api_key == f"provider_config_{config_id}"
        assert row.managed_by == handler.MANAGED_BY_PLATFORM
        assert row.workspace_id == handler.PLATFORM_WORKSPACE_ID
        assert row.is_active and row.is_public

        # The foreign key, not just the name: it is what stops the credential
        # being deleted out from under a configuration still using it.
        assert row.api_key_secret_id is not None
        secret = conn.execute(
            text("SELECT secret_name, encrypted_value FROM encrypted_secrets WHERE id = :id"),
            {"id": row.api_key_secret_id},
        ).fetchone()
        assert secret.secret_name == row.api_key
        assert secret.encrypted_value != GATEWAY_TOKEN

        instance = conn.execute(
            text("SELECT id FROM model_instances WHERE provider_config_id = :id"),
            {"id": config_id},
        ).fetchone()
        # Derived, because agents store it and billing's rate cards name it.
        assert str(instance.id) == handler.platform_instance_id(provider_spec, "test-model")


def test_reconciling_twice_updates_one_configuration(handler, provider_spec):
    """The update branch is SQL too, and is the branch that runs from then on.

    A column that exists on neither branch fails on the first reconcile; one that
    exists only on the insert fails on every reconcile after it, which is worse —
    it works once and then stops, long after the change that caused it.
    """
    config_id, _ = handler.sync_provider_config(
        _spec(provider_spec), api_key=GATEWAY_TOKEN, cr_name="test-cr"
    )

    renamed = _spec(provider_spec) | {"name": "Renamed"}
    again, _ = handler.sync_provider_config(renamed, api_key=ROTATED_TOKEN, cr_name="test-cr")

    assert again == config_id
    with handler.engine.begin() as conn:
        rows = conn.execute(
            text(
                "SELECT name, api_key_secret_id FROM provider_configs "
                "WHERE provider_spec_id = (SELECT id FROM provider_specs "
                "WHERE provider_key = :key)"
            ),
            {"key": provider_spec},
        ).fetchall()
        assert len(rows) == 1, "a second reconcile created a second configuration"
        assert rows[0].name == "Renamed"
        # Rotation writes through the same secret row rather than orphaning it.
        assert rows[0].api_key_secret_id is not None
        count = conn.execute(
            text("SELECT count(*) FROM encrypted_secrets WHERE secret_name = :n"),
            {"n": f"provider_config_{config_id}"},
        ).scalar()
        assert count == 1
