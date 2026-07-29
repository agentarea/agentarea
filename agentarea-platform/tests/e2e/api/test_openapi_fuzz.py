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
        email = f"fuzz-{uuid.uuid4().hex[:8]}@test.local"
        user = _mint_user(admin, public, email)
        return user.jwt


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
    ),
)


@_schema.parametrize()
@settings(
    # NB: per-operation example count is a speed/coverage knob, not the thing that
    # makes this suite valuable - getting it RUN in CI is. Empirically, bumping
    # 3->30 caught nothing extra on this API (219 passed either way); a 5xx that
    # fires on every valid body (e.g. a NOT NULL create bug) is caught at 3.
    max_examples=3,
    deadline=2000,
    suppress_health_check=[HealthCheck.too_slow, HealthCheck.filter_too_much],
)
@pytest.mark.integration
def test_openapi_endpoint(case: schemathesis.Case) -> None:
    case.call_and_validate(checks=(not_a_server_error,))
