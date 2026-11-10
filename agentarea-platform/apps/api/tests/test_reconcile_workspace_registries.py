"""``reconcile --workspace-registries`` syncs every registry a workspace added.

Each is synced as its own workspace (the tenant scope and the repositories'
context are the owner's, so its credentials resolve from that workspace's
secrets) with a store for a mirror registry's content; one failing does not
stop the rest. A tenant's broken source is the tenant's: it is recorded on
the registry and reported apart, and the run, which the platform's sources
decide, still succeeds.
"""

from contextlib import asynccontextmanager
from types import SimpleNamespace
from uuid import uuid4

import agentarea_registry.application.service as registry_service
import agentarea_registry.infrastructure.repository as registry_repository
from agentarea_api import cli


@asynccontextmanager
async def _always_held(_db, _key):
    yield True


async def test_every_workspace_registry_is_synced_as_its_workspace(monkeypatch, capsys):
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
        def __init__(
            self, registry_repo, *_args, credentials_resolver=None, content_mirror=None, **_kwargs
        ) -> None:
            self.context = registry_repo.user_context
            assert credentials_resolver is not None
            assert content_mirror is not None

        async def sync_registry(self, registry_id, force=False):
            if registry_id == globex.id:
                raise RuntimeError("GitHub answered 404")
            synced.append((registry_id, self.context.workspace_id, force))
            return {"source_unchanged": True}

    async def register() -> object:
        return object()

    monkeypatch.setattr(cli, "_register_graph_client", register)
    monkeypatch.setattr(cli, "_registry_sync_lock", _always_held)
    monkeypatch.setattr(cli, "Database", _Database)
    monkeypatch.setattr(cli, "get_db_settings", lambda: None)
    monkeypatch.setattr(registry_repository, "RegistryRepository", _RegistryRepository)
    monkeypatch.setattr(registry_service, "RegistryService", _RegistryService)

    await cli._reconcile(None, (), None, force=True, workspace_registries=True)

    assert synced == [(acme.id, "acme", True)]
    out = capsys.readouterr().out
    assert "Workspace registries: 1 synced, 1 failed" in out
    assert "Reconcile complete: 0 succeeded, 0 failed, 0 skipped (out of 0)" in out


async def test_a_failed_platform_source_still_fails_the_run(monkeypatch):
    import pytest

    platform = SimpleNamespace(
        id=uuid4(), recommendation_priority=None, mode="mirror", trust="official"
    )

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
            pass

        async def get_platform_by_name(self, _name):
            return platform

        async def list_active_workspace_registries(self):
            return []

    class _RegistryService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def sync_registry(self, registry_id, force=False):
            raise RuntimeError("the source answered HTTP 500")

    async def register() -> object:
        return object()

    monkeypatch.setattr(cli, "_register_graph_client", register)
    monkeypatch.setattr(cli, "_registry_sync_lock", _always_held)
    monkeypatch.setattr(cli, "Database", _Database)
    monkeypatch.setattr(cli, "get_db_settings", lambda: None)
    monkeypatch.setattr(registry_repository, "RegistryRepository", _RegistryRepository)
    monkeypatch.setattr(registry_service, "RegistryService", _RegistryService)
    config = '[{"name": "system-skills-curated", "source_url": "https://x/skills.json"}]'

    with pytest.raises(SystemExit) as exited:
        await cli._reconcile(config, (), None, workspace_registries=True)

    assert exited.value.code == 1


async def test_a_failed_unlock_does_not_replace_what_the_sync_did(caplog):
    # The lock's connection sits idle for the whole sync; when it was cut, the
    # unlock raised from finally and turned a finished sync into a failure.
    class _Conn:
        async def execution_options(self, **_options):
            return self

        async def execute(self, statement, _params):
            if "unlock" in str(statement):
                raise ConnectionResetError("connection reset by peer")
            return SimpleNamespace(scalar_one=lambda: True)

    class _Engine:
        @asynccontextmanager
        async def connect(self):
            yield _Conn()

    async with cli._registry_sync_lock(SimpleNamespace(engine=_Engine()), "k") as held:
        assert held

    assert "Could not release the reconcile lock k" in caplog.text
    assert any(r.exc_info for r in caplog.records)
