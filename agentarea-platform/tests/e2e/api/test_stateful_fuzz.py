"""Stateful OpenAPI fuzz: schemathesis drives create -> read -> update -> delete chains.

Catches sequence-dependent defects that stateless fuzz misses (e.g. resource
leaks, stale caches, half-deleted rows).

Scope of checks: 5xx detection only. Response-schema conformance and
undocumented-status checks remain out of scope until those noise sources
are cleaned up per-endpoint.
"""

from __future__ import annotations

import httpx
import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error
from schemathesis.core.errors import LoaderError

from tests.e2e.api.conftest import API_URL, FuzzCaller, pin_workspace

# Both the JWT mint and the schema load happen at import time and need the stack
# up, so @pytest.mark.integration on the test cannot help — the module fails to
# import before markers are consulted, aborting collection for the whole suite.
try:
    _CALLER = FuzzCaller("stateful")

    _schema = schemathesis.openapi.from_url(
        f"{API_URL}/openapi.json",
        headers=_CALLER.auth(),
    ).exclude(
        path_regex=(
            r".*/events/stream$"
            r"|^/webhooks/"
            r"|^/\.well-known/"
            r"|/a2a/"
            r"|^/oauth2/"
            r"|/mcp-oauth/"
            r"|/asyncapi"
            # .../agents and .../agents/ are duplicates in the spec; schemathesis
            # can't disambiguate. Keep the trailing-slash variant (canonical) only.
            r"|^/v1/workspaces/\{workspace\}/agents$"
        ),
    )
except (httpx.HTTPError, LoaderError) as exc:
    pytest.skip(
        f"Live API stack unreachable ({type(exc).__name__}): {exc}. "
        "Start it with `make up-dev`, or set FUZZ_JWT to skip the Kratos bootstrap.",
        allow_module_level=True,
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
    def before_call(self, case):  # type: ignore[override]
        pin_workspace(case, _CALLER.slug)

    def get_call_kwargs(self, case):  # type: ignore[override]
        # The schema loader's headers only fetch the spec; each call carries its own.
        return {"headers": _CALLER.auth()}

    def validate_response(self, response, case, **kwargs):  # type: ignore[override]
        case.validate_response(response, checks=(not_a_server_error,))


@pytest.mark.integration
class TestStatefulFuzz(AgentareaWorkflow.TestCase):  # type: ignore[misc, valid-type]
    """Pytest-compatible stateful test class."""

    __test__ = True
