"""The caller the live-stack fuzz pair acts as.

A Kratos identity is created through the admin API, signed in with the
password API flow, and its session exchanged for an agentarea_jwt. Nothing is
mocked: the stack must be up.

Override endpoints via env vars if your stack runs elsewhere:
    AGENTAREA_AUTH_KRATOS_ADMIN_URL   (default http://localhost:4434)
    AGENTAREA_AUTH_KRATOS_URL         (default http://localhost:4433)
    AGENTAREA_API_URL                 (default http://localhost:8000)
"""

from __future__ import annotations

import os
import time
import uuid
from dataclasses import dataclass

import httpx

KRATOS_ADMIN_URL = os.environ.get("AGENTAREA_AUTH_KRATOS_ADMIN_URL", "http://localhost:4434")
KRATOS_PUBLIC_URL = os.environ.get("AGENTAREA_AUTH_KRATOS_URL", "http://localhost:4433")
API_URL = os.environ.get("AGENTAREA_API_URL", "http://localhost:8000")

TEST_PASSWORD = "Str0ng-Test-PW-xyz!"


@dataclass
class AuthedUser:
    identity_id: str
    email: str
    session_token: str
    jwt: str


def _mint_user(admin: httpx.Client, public: httpx.Client, email: str) -> AuthedUser:
    """Create a Kratos identity with password credentials, log in, exchange to JWT."""
    resp = admin.post(
        "/admin/identities",
        json={
            "schema_id": "default",
            "traits": {"email": email},
            "credentials": {"password": {"config": {"password": TEST_PASSWORD}}},
            "verifiable_addresses": [
                {
                    "value": email,
                    "verified": True,
                    "via": "email",
                    "status": "completed",
                }
            ],
        },
    )
    resp.raise_for_status()
    identity_id = resp.json()["id"]

    flow = public.get("/self-service/login/api").raise_for_status().json()
    login = public.post(
        "/self-service/login",
        params={"flow": flow["id"]},
        json={"method": "password", "identifier": email, "password": TEST_PASSWORD},
    )
    login.raise_for_status()
    session_token = login.json()["session_token"]

    return AuthedUser(
        identity_id=identity_id,
        email=email,
        session_token=session_token,
        jwt=_tokenize(public, session_token),
    )


def personal_workspace_path(client: httpx.Client) -> str:
    """``/v1/workspaces/<slug>`` of the caller's personal workspace (provisioned on first list)."""
    workspaces = client.get("/v1/workspaces").raise_for_status().json()
    personal = next(w for w in workspaces if w["id"] == w["owner_user_id"])
    return f"/v1/workspaces/{personal['slug']}"


def _tokenize(public: httpx.Client, session_token: str) -> str:
    return (
        public.get(
            "/sessions/whoami",
            params={"tokenize_as": "agentarea_jwt"},
            headers={"X-Session-Token": session_token},
        )
        .raise_for_status()
        .json()["tokenized"]
    )


class FuzzCaller:
    """The identity a schemathesis run acts as, with a JWT that outlives the run.

    The tokenizer issues 30-minute JWTs and a full fuzz run can take longer.
    A token that lapses mid-run turns every later call into a 401, which
    ``not_a_server_error`` accepts, so the rest of the run would pass while
    exercising nothing. The Kratos session lives far longer, so the JWT is
    re-issued from it well before it expires.

    ``FUZZ_JWT`` reuses an existing token instead of minting a Kratos user; it
    is not refreshed.
    """

    _REFRESH_AFTER_SECONDS = 15 * 60

    def __init__(self, label: str) -> None:
        self._session_token: str | None = None
        jwt = os.environ.get("FUZZ_JWT")
        if not jwt:
            with (
                httpx.Client(base_url=KRATOS_ADMIN_URL, timeout=10.0) as admin,
                httpx.Client(base_url=KRATOS_PUBLIC_URL, timeout=10.0) as public,
            ):
                user = _mint_user(admin, public, f"{label}-{uuid.uuid4().hex[:8]}@test.local")
            jwt, self._session_token = user.jwt, user.session_token
        self._jwt = jwt
        self._issued_at = time.monotonic()
        with httpx.Client(
            base_url=API_URL, headers={"Authorization": f"Bearer {jwt}"}, timeout=10.0
        ) as client:
            self.slug = personal_workspace_path(client).rsplit("/", 1)[1]

    @property
    def jwt(self) -> str:
        if (
            self._session_token is not None
            and time.monotonic() - self._issued_at > self._REFRESH_AFTER_SECONDS
        ):
            with httpx.Client(base_url=KRATOS_PUBLIC_URL, timeout=10.0) as public:
                self._jwt = _tokenize(public, self._session_token)
            self._issued_at = time.monotonic()
        return self._jwt

    def auth(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.jwt}"}


def pin_workspace(case, slug: str) -> None:
    """Send a generated case to the caller's own workspace.

    ``{workspace}`` is a path parameter like any other to schemathesis, which
    fills it with arbitrary slugs: every workspace route would then answer 403
    before reaching a handler, and the fuzz would exercise nothing. Set on the
    case itself rather than through a generation hook, because the coverage
    phase builds cases without running those hooks. Foreign-slug refusal is
    asserted by its own test.
    """
    if case.path_parameters and "workspace" in case.path_parameters:
        case.path_parameters["workspace"] = slug
