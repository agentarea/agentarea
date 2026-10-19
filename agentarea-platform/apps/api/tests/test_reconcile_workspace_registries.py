"""``reconcile --workspace-registries`` syncs every registry a workspace added.

Each is synced as its own workspace (the tenant scope and the repositories'
context are the owner's, so its credentials resolve from that workspace's
secrets), one failing does not stop the rest, and the run reports it.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import agentarea_registry.application.service as registry_service
import agentarea_registry.infrastructure.repository as registry_repository
import pytest
from agentarea_api import cli


async def test_every_workspace_registry_is_synced_as_its_workspace(monkeypatch):
    acme = SimpleNamespace(id=uuid4(), name="skills", workspace_id="acme")
    globex = SimpleNamespace(id=uuid4(), name="broken", workspace_id="globex")
    synced: list[tuple] = []

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
        def __init__(self, _session, user_context=None) -> None:
            self.user_context = user_context

        async def list_active_workspace_registries(self):
            return [acme, globex]

    class _RegistryService:
        def __init__(self, registry_repo, *_args, credentials_resolver=None, **_kwargs) -> None:
            self.context = registry_repo.user_context
            assert credentials_resolver is not None

        async def sync_registry(self, registry_id, force=False):
            if registry_id == globex.id:
                raise RuntimeError("GitHub answered 404")
            synced.append((registry_id, self.context.workspace_id, force))
            return {"source_unchanged": True}

    async def register() -> object:
        return object()

    monkeypatch.setattr(cli, "_register_graph_client", register)
    monkeypatch.setattr(cli, "Database", _Database)
    monkeypatch.setattr(cli, "get_db_settings", lambda: None)
    monkeypatch.setattr(registry_repository, "RegistryRepository", _RegistryRepository)
    monkeypatch.setattr(registry_service, "RegistryService", _RegistryService)

    with pytest.raises(SystemExit) as exited:
        await cli._reconcile(None, (), None, force=True, workspace_registries=True)

    assert exited.value.code == 1
    assert synced == [(acme.id, "acme", True)]
