"""Whose secrets a call reads, and why getting it wrong is invisible.

Both kinds of provider configuration store a secret *name*; what differs is the
workspace the name is looked up in. A platform reference resolved against the
caller's workspace finds nothing, and so does a tenant reference resolved against
the platform's. Both produce a request with no key and a 401 from the provider,
attributed to the user's credentials — which is the one explanation that is never
right. Nothing else in the system notices, so it is checked here.
"""

from types import SimpleNamespace

import pytest
from agentarea_common.constants import (
    MANAGED_BY_PLATFORM,
    PLATFORM_WORKSPACE_ID,
)
from agentarea_execution.activities.agent_execution_activities import (
    _resolve_provider_api_key,
)
from agentarea_execution.models import LLMCallRequest, ResolvedModelInfo

TENANT_WORKSPACE = "ws"

# Deliberately the same name in both workspaces. A tenant can choose what to call
# their own secrets, so the names are not a namespace — the workspace is.
SHARED_REFERENCE = "openai"


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


class _WorkspaceScopedStore:
    """Stands in for DatabaseSecretManager: sees one workspace's secrets only."""

    def __init__(self, values, asked):
        self._values = values
        self._asked = asked

    async def get_secret(self, name):
        self._asked.append(name)
        return self._values.get(name)


class _RecordingFactory:
    """Hands out a store per workspace and remembers which context asked."""

    def __init__(self, by_workspace):
        self._by_workspace = by_workspace
        self.contexts = []
        self.asked_by_workspace = {ws: [] for ws in by_workspace}

    def create(self, *, session, user_context):
        self.contexts.append(user_context)
        workspace = user_context.workspace_id
        return _WorkspaceScopedStore(
            self._by_workspace.get(workspace, {}),
            self.asked_by_workspace.setdefault(workspace, []),
        )


class _Dependencies:
    def __init__(self, factory):
        self.secret_manager_factory = factory


@pytest.fixture
def factory(monkeypatch):
    built = _RecordingFactory(
        {
            TENANT_WORKSPACE: {SHARED_REFERENCE: "tenant-key"},
            PLATFORM_WORKSPACE_ID: {SHARED_REFERENCE: "platform-key"},
        }
    )

    # Building a secret manager opens a database session. The routing is what this
    # test is about, so the session is stubbed out.
    class _Session:
        async def close(self):
            return None

    monkeypatch.setattr(
        "agentarea_common.config.get_database",
        lambda: SimpleNamespace(async_session_factory=lambda: _Session()),
    )
    return built


async def test_tenant_config_reads_the_callers_workspace(factory):
    key = await _resolve_provider_api_key(
        reference=SHARED_REFERENCE,
        managed_by=None,
        user_context=SimpleNamespace(workspace_id=TENANT_WORKSPACE, user_id="u"),
        dependencies=_Dependencies(factory),
    )

    assert key == "tenant-key"
    assert [c.workspace_id for c in factory.contexts] == [TENANT_WORKSPACE]


async def test_platform_config_reads_the_platform_workspace_not_the_callers(factory):
    """The important one: the caller's workspace must not even be consulted.

    Both workspaces hold a secret under this exact name. If the caller's context
    were used, a tenant could name a secret after the platform's reference and
    have their own value served in place of the operator's — on a configuration
    they are deliberately allowed to see but not to write.
    """
    key = await _resolve_provider_api_key(
        reference=SHARED_REFERENCE,
        managed_by=MANAGED_BY_PLATFORM,
        user_context=SimpleNamespace(workspace_id=TENANT_WORKSPACE, user_id="u"),
        dependencies=_Dependencies(factory),
    )

    assert key == "platform-key"
    assert [c.workspace_id for c in factory.contexts] == [PLATFORM_WORKSPACE_ID]
    assert factory.asked_by_workspace[TENANT_WORKSPACE] == [], (
        "the caller's secret store was consulted for a platform credential"
    )


async def test_a_platform_credential_the_operator_never_set_is_not_an_error(factory):
    """A configuration whose secret is missing sends no key rather than crashing.

    Returning None sends the request without an Authorization header, which is
    also the correct behaviour for an endpoint that authenticates with nothing.
    """
    key = await _resolve_provider_api_key(
        reference="never-created",
        managed_by=MANAGED_BY_PLATFORM,
        user_context=SimpleNamespace(workspace_id=TENANT_WORKSPACE, user_id="u"),
        dependencies=_Dependencies(factory),
    )

    assert key is None


async def test_no_reference_touches_no_store(factory):
    """A keyless provider must not produce a lookup for the empty name."""
    key = await _resolve_provider_api_key(
        reference=None,
        managed_by=None,
        user_context=SimpleNamespace(workspace_id=TENANT_WORKSPACE, user_id="u"),
        dependencies=_Dependencies(factory),
    )

    assert key is None
    assert factory.contexts == []
