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


async def test_reconcile_repairs_graph_ownership_even_with_no_registry_configured(
    monkeypatch,
) -> None:
    from agentarea_api import cli

    calls: list[str] = []
    client = object()

    async def register() -> object:
        calls.append("register")
        return client

    async def ownership(db, graph) -> None:
        assert graph is client
        calls.append("ownership")

    monkeypatch.setattr(cli, "_register_graph_client", register)
    monkeypatch.setattr(cli, "_reconcile_graph_ownership", ownership)

    await cli._reconcile(None, (), None)

    assert calls == ["register", "ownership"]
