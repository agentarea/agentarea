"""Reconciling the same resource again lands on the rows it wrote last time (#708).

kopf reconciles a resource on create, on every update, on the hourly rediscovery
timer and on every operator restart. A platform resource always converged on one
configuration because its ids are derived; a workspace-scoped one (``workspaceId``
set) generated fresh ids, so each of those reconciles inserted another provider
configuration, another encrypted copy of the key and another set of model
instances — and an update rotated the key into a new row instead of the old one.

The fake below keeps the rows the handler's SQL would write, keyed the way the
real schema's unique constraints key them, so the counts are what Postgres would
end up holding.
"""

from contextlib import contextmanager
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet

import handler

API_KEY = "sk-live"  # pragma: allowlist secret
ROTATED_KEY = "sk-rotated"  # pragma: allowlist secret
FERNET_KEY = Fernet.generate_key().decode()


class _Result:
    def __init__(self, row=None):
        self._row = row

    def fetchone(self):
        return self._row


class FakeDB:
    """The tables a provider-config reconcile touches, as plain dicts."""

    def __init__(self):
        self.provider_configs: dict[str, dict] = {}
        self.secrets: dict[tuple[str, str], dict] = {}  # (workspace, name) is unique
        self.model_specs: dict[tuple[str, str, str], str] = {}
        self.model_instances: dict[str, dict] = {}

    def execute(self, statement, params=None):
        sql, p = str(statement), params or {}

        if sql.startswith("SELECT id FROM provider_specs"):
            return _Result(("provider-spec-1",))

        if sql.startswith("SELECT id FROM provider_configs"):
            return _Result((p["id"],) if p["id"] in self.provider_configs else None)

        if sql.startswith("INSERT INTO encrypted_secrets"):
            # ON CONFLICT (workspace_id, secret_name) DO UPDATE ... RETURNING id
            key = (p["ws"], p["name"])
            row = self.secrets.setdefault(key, {"id": p["id"]})
            row["encrypted_value"] = p["val"]
            return _Result((row["id"],))

        if sql.startswith("INSERT INTO provider_configs"):
            assert p["id"] not in self.provider_configs, "duplicate primary key"
            self.provider_configs[p["id"]] = dict(p)
            return _Result()

        if sql.startswith("UPDATE provider_configs"):
            self.provider_configs[p["id"]].update(p)
            return _Result()

        if sql.startswith("SELECT id FROM model_specs"):
            spec_id = self.model_specs.get((p["spec_id"], p["mn"], p["ws"]))
            return _Result((spec_id,) if spec_id else None)

        if sql.startswith("INSERT INTO model_specs"):
            self.model_specs[(p["spec_id"], p["mn"], p["ws"])] = p["id"]
            return _Result()

        if sql.startswith("UPDATE model_specs"):
            return _Result()

        if sql.startswith("SELECT id FROM model_instances"):
            for instance_id, row in self.model_instances.items():
                if instance_id == p["id"] or (
                    row["cid"] == p["cid"] and row["msid"] == p["msid"]
                ):
                    return _Result((instance_id,))
            return _Result()

        if sql.startswith("INSERT INTO model_instances"):
            assert p["id"] not in self.model_instances, "duplicate primary key"
            self.model_instances[p["id"]] = dict(p)
            return _Result()

        if sql.startswith("UPDATE model_instances"):
            self.model_instances[p["id"]]["tags"] = p["tags"]
            return _Result()

        raise AssertionError(f"unexpected statement: {sql}")

    def secret_value(self, workspace_id: str, config_id: str) -> str:
        row = self.secrets[(workspace_id, handler.secret_name_for(config_id))]
        return Fernet(FERNET_KEY.encode()).decrypt(row["encrypted_value"].encode()).decode()


@pytest.fixture
def db(monkeypatch):
    fake = FakeDB()

    @contextmanager
    def begin():
        yield fake

    monkeypatch.setattr(handler, "engine", Mock(begin=begin))
    monkeypatch.setattr(handler, "ENCRYPTION_KEY", FERNET_KEY)
    return fake


def _spec(workspace_id: str) -> dict:
    return {
        "providerKey": "openai",
        "name": "Team OpenAI",
        "workspaceId": workspace_id,
        "models": [{"modelName": "gpt-4o"}, {"modelName": "gpt-4o-mini"}],
    }


def _reconcile(spec: dict, api_key: str = API_KEY, cr_name: str = "team-openai") -> str:
    config_id, _ = handler.sync_provider_config(
        spec, api_key, cr_name, namespace="team-a"
    )
    return config_id


@pytest.mark.parametrize("workspace_id", [handler.PLATFORM_WORKSPACE_ID, "ws-123"])
def test_reconciling_a_resource_again_writes_no_new_rows(db, workspace_id):
    """Create, then an update, the hourly timer and a restart: still one of each."""
    ids = {_reconcile(_spec(workspace_id)) for _ in range(3)}

    assert len(ids) == 1, "each reconcile reported a different configuration"
    assert len(db.provider_configs) == 1, (
        f"{len(db.provider_configs)} provider configurations after 3 reconciles"
    )
    assert len(db.secrets) == 1, f"{len(db.secrets)} encrypted secrets after 3 reconciles"
    assert len(db.model_instances) == 2, (
        f"{len(db.model_instances)} model instances for 2 models after 3 reconciles"
    )
    (config_id,) = ids
    assert all(row["cid"] == config_id for row in db.model_instances.values())


def test_updating_a_workspace_resource_rotates_the_key_in_its_existing_secret(db):
    """An update changes the rows the resource already owns, the key included."""
    config_id = _reconcile(_spec("ws-123"))
    secret_id = db.provider_configs[config_id]["secret_id"]
    assert db.secret_value("ws-123", config_id) == API_KEY

    updated = _spec("ws-123") | {"name": "Team OpenAI (prod)"}
    again = _reconcile(updated, api_key=ROTATED_KEY)

    assert again == config_id
    assert len(db.provider_configs) == 1
    assert db.provider_configs[config_id]["name"] == "Team OpenAI (prod)"
    assert len(db.secrets) == 1, "the rotated key went into a second secret"
    assert db.provider_configs[config_id]["secret_id"] == secret_id
    assert db.secret_value("ws-123", config_id) == ROTATED_KEY


def test_distinct_workspace_resources_get_distinct_configurations(db):
    """Derived from the resource, so two resources do not collapse into one row."""
    a = _reconcile(_spec("ws-123"), cr_name="team-openai")
    b = _reconcile(_spec("ws-123"), cr_name="team-openai-batch")
    c = _reconcile(_spec("ws-456"), cr_name="team-openai")

    assert len({a, b, c}) == 3
    assert len(db.provider_configs) == 3
    assert handler.PLATFORM_WORKSPACE_ID not in {
        row["ws"] for row in db.provider_configs.values()
    }


def test_workspace_ids_are_frozen():
    """The recipe is what finds last reconcile's rows; changing it duplicates them all."""
    assert (
        handler.workspace_config_id("ws-123", "team-a", "team-openai", "openai")
        == "b6afbad9-2b77-52ab-bd5e-f28644e0f5af"
    )
    assert (
        handler.workspace_instance_id("b6afbad9-2b77-52ab-bd5e-f28644e0f5af", "gpt-4o")
        == "08235810-6a0f-5eea-92e0-ee5050a20da4"
    )
