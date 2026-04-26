"""Stateful OpenAPI fuzz: schemathesis drives create -> read -> update -> delete chains.

Catches sequence-dependent defects that stateless fuzz misses (e.g. resource
leaks, stale caches, half-deleted rows).

Scope of checks: 5xx detection only. Response-schema conformance and
undocumented-status checks remain out of scope until those noise sources
are cleaned up per-endpoint.
"""

from __future__ import annotations

import os
import uuid

import httpx
import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error

from tests.e2e.api.conftest import (
    API_URL,
    KRATOS_ADMIN_URL,
    KRATOS_PUBLIC_URL,
    _mint_user,
)


def _bootstrap_jwt() -> str:
    with (
        httpx.Client(base_url=KRATOS_ADMIN_URL, timeout=10.0) as admin,
        httpx.Client(base_url=KRATOS_PUBLIC_URL, timeout=10.0) as public,
    ):
        email = f"stateful-{uuid.uuid4().hex[:8]}@test.local"
        return _mint_user(admin, public, email).jwt


_JWT = os.environ.get("FUZZ_JWT") or _bootstrap_jwt()

_schema = schemathesis.openapi.from_url(
    f"{API_URL}/openapi.json",
    headers={"Authorization": f"Bearer {_JWT}"},
).exclude(
    path_regex=(
        r".*/events/stream$"
        r"|^/webhooks/"
        r"|^/\.well-known/"
        r"|/a2a/"
        r"|^/oauth2/"
        r"|/mcp-oauth/"
        r"|/asyncapi"
        # /v1/agents and /v1/agents/ are duplicates in the spec; schemathesis
        # can't disambiguate. Keep the trailing-slash variant (canonical) only.
        r"|^/v1/agents$"
    ),
)

BaseWorkflow = _schema.as_state_machine()


@settings(
    max_examples=20,
    stateful_step_count=6,
    deadline=None,
    suppress_health_check=[
        HealthCheck.too_slow,
        HealthCheck.filter_too_much,
        HealthCheck.data_too_large,
    ],
)
class AgentareaWorkflow(BaseWorkflow):  # type: ignore[misc, valid-type]
    def validate_response(self, response, case, **kwargs):  # type: ignore[override]
        case.validate_response(response, checks=(not_a_server_error,))


@pytest.mark.integration
class TestStatefulFuzz(AgentareaWorkflow.TestCase):  # type: ignore[misc, valid-type]
    """Pytest-compatible stateful test class."""

    __test__ = True
