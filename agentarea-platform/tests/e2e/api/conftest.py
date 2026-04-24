"""Fixtures for local end-to-end API tests.

These tests exercise the real running stack (Kratos admin + public, backend API).
They do NOT mock anything. Each test run provisions ephemeral Kratos identities
via the admin API, exchanges session tokens for agentarea_jwt, and tears the
identities down on fixture teardown.

Run with:
    uv run pytest -m integration tests/e2e/api/ -v

Override endpoints via env vars if your stack runs elsewhere:
    KRATOS_ADMIN_URL   (default http://localhost:4434)
    KRATOS_PUBLIC_URL  (default http://localhost:4433)
    API_URL            (default http://localhost:8000)
"""

from __future__ import annotations

import os
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass

import httpx
import pytest

KRATOS_ADMIN_URL = os.environ.get("KRATOS_ADMIN_URL", "http://localhost:4434")
KRATOS_PUBLIC_URL = os.environ.get("KRATOS_PUBLIC_URL", "http://localhost:4433")
API_URL = os.environ.get("API_URL", "http://localhost:8000")

TEST_PASSWORD = "Str0ng-Test-PW-xyz!"


@dataclass
class AuthedUser:
    identity_id: str
    email: str
    session_token: str
    jwt: str


# Pytest treats any top-level class whose name starts with "Test" as a test
# class and warns if it has __init__. Keep the alias for backward compat.
TestUser = AuthedUser
TestUser.__test__ = False  # type: ignore[attr-defined]


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

    tokenized = public.get(
        "/sessions/whoami",
        params={"tokenize_as": "agentarea_jwt"},
        headers={"X-Session-Token": session_token},
    ).raise_for_status().json()["tokenized"]

    return AuthedUser(identity_id=identity_id, email=email, session_token=session_token, jwt=tokenized)


@pytest.fixture(scope="session")
def kratos_admin() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=KRATOS_ADMIN_URL, timeout=10.0) as client:
        yield client


@pytest.fixture(scope="session")
def kratos_public() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=KRATOS_PUBLIC_URL, timeout=10.0) as client:
        yield client


@pytest.fixture
def user_factory(
    kratos_admin: httpx.Client, kratos_public: httpx.Client
) -> Iterator[Callable[[str | None], AuthedUser]]:
    """Mint ephemeral Kratos users; delete them on teardown."""
    created: list[str] = []

    def factory(label: str | None = None) -> AuthedUser:
        prefix = label or "user"
        email = f"{prefix}-{uuid.uuid4().hex[:8]}@test.local"
        user = _mint_user(kratos_admin, kratos_public, email)
        created.append(user.identity_id)
        return user

    yield factory

    for identity_id in created:
        try:
            kratos_admin.delete(f"/admin/identities/{identity_id}")
        except httpx.HTTPError:
            pass


@pytest.fixture
def alice(user_factory: Callable[[str | None], AuthedUser]) -> AuthedUser:
    return user_factory("alice")


@pytest.fixture
def bob(user_factory: Callable[[str | None], AuthedUser]) -> AuthedUser:
    return user_factory("bob")


def _authed_client(token: str) -> httpx.Client:
    return httpx.Client(
        base_url=API_URL,
        headers={"Authorization": f"Bearer {token}"},
        timeout=10.0,
    )


@pytest.fixture
def alice_client(alice: AuthedUser) -> Iterator[httpx.Client]:
    with _authed_client(alice.jwt) as client:
        yield client


@pytest.fixture
def bob_client(bob: AuthedUser) -> Iterator[httpx.Client]:
    with _authed_client(bob.jwt) as client:
        yield client


@pytest.fixture
def anon_client() -> Iterator[httpx.Client]:
    with httpx.Client(base_url=API_URL, timeout=10.0) as client:
        yield client
