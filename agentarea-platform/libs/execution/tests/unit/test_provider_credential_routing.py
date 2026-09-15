"""Which credential store a call reads, and why getting it wrong is invisible.

A platform reference sent to the tenant's secret manager resolves to None. A tenant
secret name looked up in the environment resolves to None. Both produce a request
with no key and a 401 from the provider, attributed to the user's credentials —
which is the one explanation that is never right. Nothing else in the system
notices, so it is checked here.
"""

from types import SimpleNamespace

import pytest
from agentarea_common.infrastructure.platform_credentials import MANAGED_BY_PLATFORM
from agentarea_execution.activities.agent_execution_activities import (
    _resolve_provider_api_key,
)
from agentarea_execution.models import LLMCallRequest, ResolvedModelInfo


def _resolved(**overrides):
    base = {
        "model_id": "m-1",
        "provider_type": "openai",
        "model_name": "gpt-4o-mini",
        "context_window": 128000,
    }
    return ResolvedModelInfo(**{**base, **overrides})


def test_managed_by_survives_the_dict_round_trip():
    """``managed_by`` must reach the governance gate under exactly this name.

    The workflow caches the resolved model as a plain dict on LLMCallRequest, the
    temporal bridge turns the whole request into action_params via model_dump(),
    and the enterprise entitlement guard reads
    ``action_params["resolved_model"]["managed_by"]`` to decide whether an
    unverifiable call is about to spend OUR provider credit or the customer's.

    Nothing in this repository imports that guard, so renaming or dropping the
    field breaks it silently and in the expensive direction: the guard would read
    None, conclude BYOK, and fall back to allowing when billing is unreachable —
    on calls we are paying for. This pins the wire name.
    """
    cached = _resolved(managed_by=MANAGED_BY_PLATFORM).model_dump()
    assert cached["managed_by"] == "platform"

    request = LLMCallRequest(messages=[], model_id="m-1", resolved_model=cached)
    action_params = request.model_dump()
    assert action_params["resolved_model"]["managed_by"] == "platform"


def test_a_tenant_model_says_so_rather_than_omitting_the_field():
    """Absent and "not platform" are different answers, and the guard treats them so.

    A missing key means "this request cannot tell you", which the guard resolves
    against the deployment's own configuration. An explicit None means "the
    customer's own key", which it can trust. Round-tripping must preserve that
    distinction rather than collapsing both to a missing key.
    """
    cached = _resolved().model_dump()
    assert "managed_by" in cached, "the field must be present even when it is None"
    assert cached["managed_by"] is None


class _TenantSecretManager:
    """Stands in for the workspace-scoped store, and records that it was consulted."""

    def __init__(self, values):
        self.values = values
        self.asked_for: list[str] = []

    async def get_secret(self, name):
        self.asked_for.append(name)
        return self.values.get(name)


class _Dependencies:
    def __init__(self, manager):
        self._manager = manager
        self.secret_manager_factory = SimpleNamespace(create=lambda **_: manager)


@pytest.fixture
def tenant_store(monkeypatch):
    manager = _TenantSecretManager({"provider_config_abc": "tenant-key"})

    # The tenant path opens a database session to build its secret manager. The
    # store itself is what this test is about, so the session is stubbed out.
    class _Session:
        async def close(self):
            return None

    monkeypatch.setattr(
        "agentarea_common.config.get_database",
        lambda: SimpleNamespace(async_session_factory=lambda: _Session()),
    )
    return manager


async def test_tenant_config_reads_the_workspace_secret_store(tenant_store, monkeypatch):
    monkeypatch.setenv("PLATFORM_CREDENTIAL_PROVIDER_CONFIG_ABC", "platform-key")

    key = await _resolve_provider_api_key(
        reference="provider_config_abc",
        managed_by=None,
        user_context=SimpleNamespace(workspace_id="ws", user_id="u"),
        dependencies=_Dependencies(tenant_store),
    )

    assert key == "tenant-key"
    assert tenant_store.asked_for == ["provider_config_abc"]


async def test_platform_config_reads_the_environment_not_the_workspace(
    tenant_store, monkeypatch
):
    """The important one: the tenant store must not even be consulted.

    If it were, a tenant could create a secret named after the platform's
    credential reference and have their own value served in its place.
    """
    monkeypatch.setenv("PLATFORM_CREDENTIAL_OPENAI", "platform-key")

    key = await _resolve_provider_api_key(
        reference="openai",
        managed_by=MANAGED_BY_PLATFORM,
        user_context=SimpleNamespace(workspace_id="ws", user_id="u"),
        dependencies=_Dependencies(tenant_store),
    )

    assert key == "platform-key"
    assert tenant_store.asked_for == [], "the tenant secret store was consulted"


async def test_platform_credential_absent_yields_no_key_rather_than_an_error(
    tenant_store, monkeypatch
):
    """An operator who declared a model and forgot its key gets a warning, not a crash.

    Returning None sends the request without an Authorization header, which is
    also the correct behaviour for an endpoint that authenticates with nothing.
    """
    monkeypatch.delenv("PLATFORM_CREDENTIAL_OPENAI", raising=False)

    key = await _resolve_provider_api_key(
        reference="openai",
        managed_by=MANAGED_BY_PLATFORM,
        user_context=SimpleNamespace(workspace_id="ws", user_id="u"),
        dependencies=_Dependencies(tenant_store),
    )

    assert key is None


async def test_no_reference_touches_no_store(tenant_store):
    """A keyless provider must not produce a lookup for the empty name."""
    key = await _resolve_provider_api_key(
        reference=None,
        managed_by=None,
        user_context=SimpleNamespace(workspace_id="ws", user_id="u"),
        dependencies=_Dependencies(tenant_store),
    )

    assert key is None
    assert tenant_store.asked_for == []
