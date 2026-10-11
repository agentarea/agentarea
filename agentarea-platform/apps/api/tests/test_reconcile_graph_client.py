"""The registry reconcile job reaches the authorization graph with its own env.

The CronJob gets the database and access-control env, not the worker's
Temporal settings. Resolving the graph client once loaded every settings
domain, so a job that never touches Temporal failed the Temporal settings
validation: first per catalog item ("Skipping catalog item ... validation error
for WorkflowSettings"), then, once the client was registered up front, the
whole run.
"""

import pytest
from agentarea_api.cli import _register_graph_client
from agentarea_common.config import get_settings
from agentarea_common.di.container import get_container
from agentarea_common.rebac.openfga_client import OpenFGAClient
from agentarea_common.rebac.ownership import resolve_graph_client


@pytest.fixture
def reconcile_job_env(monkeypatch):
    for name in (
        "AGENTAREA_TASK_EXECUTOR",
        "TEMPORAL_ADDRESS",
        "TEMPORAL_NAMESPACE",
        "AGENTAREA_TEMPORAL_QUEUE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("AGENTAREA_AUTHZ_BACKEND", "openfga")
    monkeypatch.setenv("AGENTAREA_AUTHZ_FGA_STORE_ID", "store-1")
    monkeypatch.setenv("AGENTAREA_AUTHZ_FGA_BOOTSTRAP", "false")
    monkeypatch.setattr(get_container(), "_singletons", {})
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_reconcile_resolves_the_graph_client_without_temporal_settings(
    reconcile_job_env,
) -> None:
    await _register_graph_client()

    assert isinstance(resolve_graph_client(), OpenFGAClient)


async def test_only_the_post_migration_run_repairs_graph_ownership(monkeypatch) -> None:
    from agentarea_api import cli

    calls: list[str] = []
    client = object()

    async def register() -> object:
        return client

    async def ownership(db, graph) -> None:
        assert graph is client
        calls.append("ownership")

    monkeypatch.setattr(cli, "_register_graph_client", register)
    monkeypatch.setattr(cli, "_reconcile_graph_ownership", ownership)

    await cli._reconcile(None, (), None)
    assert calls == []
    await cli._reconcile(None, (), None, repair_ownership=True)
    assert calls == ["ownership"]


async def test_a_retired_manifest_entry_deactivates_its_registry_without_syncing(
    monkeypatch,
) -> None:
    from contextlib import asynccontextmanager
    from types import SimpleNamespace
    from uuid import uuid4

    import agentarea_registry.application.service as registry_service
    import agentarea_registry.infrastructure.repository as registry_repository
    from agentarea_api import cli

    live = SimpleNamespace(id=uuid4(), name="system-openapi-connections", is_active=True)
    calls: list[tuple] = []

    class _Session:
        async def commit(self) -> None:
            pass

    class _Database:
        def __init__(self, *_args) -> None:
            pass

        @asynccontextmanager
        async def async_session_factory(self):
            yield _Session()

    class _RegistryRepository:
        def __init__(self, *_args) -> None:
            pass

        async def list_all(self):
            return [live]

    class _RegistryService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def update_registry(self, registry_id, **fields):
            calls.append(("update", registry_id, fields))

        async def sync_registry(self, registry_id):
            calls.append(("sync", registry_id))
            return {}

    async def register() -> object:
        return object()

    monkeypatch.setattr(cli, "_register_graph_client", register)
    monkeypatch.setattr(cli, "Database", _Database)
    monkeypatch.setattr(cli, "get_db_settings", lambda: None)
    monkeypatch.setattr(registry_repository, "RegistryRepository", _RegistryRepository)
    monkeypatch.setattr(registry_service, "RegistryService", _RegistryService)

    retired = '[{"name": "system-openapi-connections", "active": false}]'
    await cli._reconcile(retired, (), None)
    assert calls == [("update", live.id, {"is_active": False})]

    live.is_active = False
    calls.clear()
    await cli._reconcile(retired, (), None)
    assert calls == []
