"""OpenAPI-driven smoke fuzz with schemathesis.

Scope: detect 5xx responses across every documented endpoint, at minimum effort.
Does NOT enforce schema conformance of responses (many endpoints legitimately
return undocumented 400s for oauth/preview flows — that's a separate cleanup).

Wider checks (response schema conformance, undocumented statuses, negative data
rejection) can be enabled per-endpoint once the base suite is green.

Complements handwritten tests; it is not a replacement for explicit business
flow tests.
"""

from __future__ import annotations

import uuid

import httpx
import pytest
import schemathesis
from hypothesis import HealthCheck, settings
from schemathesis.checks import not_a_server_error
from schemathesis.core.errors import LoaderError

from tests.e2e.api.conftest import API_URL, FuzzCaller, pin_workspace

# Minting a JWT and loading the schema both need the stack up, and both run at
# import time — so @pytest.mark.integration on the test below cannot help: the
# module fails to import before any marker is consulted, which aborts collection
# for the ENTIRE suite, not just this file. Skip at module level instead.
try:
    _CALLER = FuzzCaller("fuzz")

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
        ),
    )
except (httpx.HTTPError, LoaderError) as exc:
    pytest.skip(
        f"Live API stack unreachable ({type(exc).__name__}): {exc}. "
        "Start it with `make up-dev`, or set FUZZ_JWT to skip the Kratos bootstrap.",
        allow_module_level=True,
    )


@_schema.parametrize()
@settings(
    # NB: per-operation example count is a speed/coverage knob, not the thing that
    # makes this suite valuable - getting it RUN in CI is. Empirically, bumping
    # 3->30 caught nothing extra on this API (219 passed either way); a 5xx that
    # fires on every valid body (e.g. a NOT NULL create bug) is caught at 3.
    max_examples=3,
    # Real handlers run now, and their latency tracks runner load; the 10s request
    # timeout still fails a hang, which is all a deadline here would catch.
    deadline=None,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@pytest.mark.integration
def test_openapi_endpoint(case: schemathesis.Case) -> None:
    pin_workspace(case, _CALLER.slug)
    # The schema loader's headers only fetch the spec; each call carries its own.
    response = case.call(headers=_CALLER.auth())
    if _is_declared_unavailability(case, response.status_code):
        return
    case.validate_response(response, checks=(not_a_server_error,))


# Operations whose backing service this stack does not run, and the status each
# one documents for exactly that. The status must stay in the operation's spec:
# drop it there and the tolerance goes with it.
#   sandboxes: the job starts no sandbox manager and sets no
#   SANDBOX_INSPECTION_AUTH_SECRET, so the inventory is "not configured".
#   mcp-server-instances/check: validation is delegated to the MCP manager,
#   which the job does not start.
_UNAVAILABLE_IN_THIS_STACK = {
    "GET /v1/workspaces/{workspace}/sandboxes": 503,
    "POST /v1/workspaces/{workspace}/mcp-server-instances/check": 503,
}


def _is_declared_unavailability(case: schemathesis.Case, status_code: int) -> bool:
    expected = _UNAVAILABLE_IN_THIS_STACK.get(case.operation.label)
    documented = case.operation.definition.raw.get("responses", {})
    return status_code == expected and str(expected) in documented


@pytest.mark.integration
def test_a_workspace_the_caller_does_not_reach_is_forbidden() -> None:
    """The pinned slug is not a blind spot: a random one is refused before any handler."""
    foreign = f"fuzz-foreign-{uuid.uuid4().hex[:10]}"
    with httpx.Client(base_url=API_URL, headers=_CALLER.auth(), timeout=10.0) as client:
        own = client.get(f"/v1/workspaces/{_CALLER.slug}/agents/")
        refused = client.get(f"/v1/workspaces/{foreign}/agents/")

    assert own.status_code == 200, own.text[:200]
    assert refused.status_code == 403, refused.text[:200]
