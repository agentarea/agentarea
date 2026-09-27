"""The registry reconcile job reaches the authorization graph with its own env.

The CronJob gets the database and access-control env, not the worker's
Temporal settings. Resolving the graph client once loaded every settings
domain, so a job that never touches Temporal failed WorkflowSettings
validation: first per catalog item ("Skipping catalog item ... validation error
for WorkflowSettings"), then, once the client was registered up front, the
whole run.
"""

import pytest
from agentarea_api.cli import _register_graph_client
from agentarea_common.config import get_settings
from agentarea_common.di.container import get_container
from agentarea_common.rebac.keto_client import KetoClient
from agentarea_common.rebac.ownership import resolve_graph_client


@pytest.fixture
def reconcile_job_env(monkeypatch):
    for name in (
        "WORKFLOW__EXECUTION_ENGINE",
        "WORKFLOW__TEMPORAL_SERVER_URL",
        "WORKFLOW__TEMPORAL_NAMESPACE",
        "WORKFLOW__TEMPORAL_TASK_QUEUE",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ACCESS_CONTROL_BACKEND", "keto")
    monkeypatch.setattr(get_container(), "_singletons", {})
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


async def test_reconcile_resolves_the_graph_client_without_temporal_settings(
    reconcile_job_env,
) -> None:
    await _register_graph_client()

    resolved = resolve_graph_client()

    assert resolved is not None
    client, backend = resolved
    assert isinstance(client, KetoClient)
    assert backend == "Keto"
