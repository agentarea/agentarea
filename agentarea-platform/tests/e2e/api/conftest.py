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


# ---------------------------------------------------------------------------
# LLM fixture: any OpenAI-compatible endpoint (seeds provider_spec +
# model_spec in the system workspace, then creates per-test provider_config
# and model_instance).
#
# Defaults target a local OpenAI-compatible router reachable from the
# backend container at host.docker.internal:20128 (e.g. Omniroute / LiteLLM
# Proxy / any proxy exposing /v1/chat/completions). Any other endpoint works
# the same way — pass OPENAI_COMPAT_* env vars.
# ---------------------------------------------------------------------------

LLM_ENDPOINT = os.environ.get(
    "OPENAI_COMPAT_ENDPOINT", "http://host.docker.internal:20128/v1"
)
LLM_MODEL = os.environ.get("OPENAI_COMPAT_MODEL", "kr/claude-sonnet-4.5")
# The backend suppresses the Authorization header when api_key is empty
# (see llm_model.py:302 — `if self.api_key:`). Default empty so proxies that
# accept keyless traffic (e.g. Omniroute with REQUIRE_API_KEY=false) work
# out of the box. Set this for endpoints that actually require a key.
LLM_API_KEY = os.environ.get("OPENAI_COMPAT_API_KEY", "")
# Stable slug for the provider_spec we create; decoupled from any vendor.
LLM_PROVIDER_KEY = os.environ.get("OPENAI_COMPAT_PROVIDER_KEY", "e2e-openai-compat")

_POSTGRES_CONTAINER = os.environ.get("POSTGRES_CONTAINER", "agentarea-db-1")
_POSTGRES_DB = os.environ.get("POSTGRES_DB_NAME", "agentarea")


def _psql(sql: str) -> str:
    import subprocess

    result = subprocess.run(
        ["docker", "exec", _POSTGRES_CONTAINER, "/usr/bin/psql",
         "-U", "postgres", "-d", _POSTGRES_DB, "-tA", "-c", sql],
        check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


@pytest.fixture(scope="session")
def llm_provider_spec_id() -> str:
    """Seed a system-scoped OpenAI-compatible provider_spec if missing.

    Provider specs have no POST endpoint (they're normally seeded via registry
    sync). For local e2e we INSERT via SQL into workspace_id='system' so every
    authenticated user can reference it.
    """
    _psql(
        "INSERT INTO provider_specs(id,provider_key,name,provider_type,"
        "is_builtin,workspace_id,created_by) "
        f"VALUES (gen_random_uuid(),'{LLM_PROVIDER_KEY}',"
        "'OpenAI-compatible (e2e)','openai-compatible',true,'system','system') "
        "ON CONFLICT (provider_key) DO NOTHING;"
    )
    spec_id = _psql(
        f"SELECT id FROM provider_specs WHERE provider_key='{LLM_PROVIDER_KEY}';"
    )
    assert spec_id, "failed to seed provider_spec"
    return spec_id


@pytest.fixture(scope="session")
def llm_model_spec_id(llm_provider_spec_id: str) -> str:
    """Seed a system-scoped model_spec for the configured model.

    model_specs has a (provider_spec_id, model_name) unique constraint that is
    NOT workspace-scoped, so a per-user POST breaks on re-run. Seed once in
    workspace='system' and let all users read it via their accessible list.
    Also promotes any pre-existing rows to system workspace.
    """
    _psql(
        "UPDATE model_specs SET workspace_id='system', created_by='system' "
        f"WHERE provider_spec_id='{llm_provider_spec_id}' "
        f"AND model_name='{LLM_MODEL}';"
    )
    _psql(
        "INSERT INTO model_specs(id,provider_spec_id,model_name,display_name,"
        "context_window,is_active,workspace_id,created_by) VALUES "
        f"(gen_random_uuid(),'{llm_provider_spec_id}','{LLM_MODEL}',"
        f"'{LLM_MODEL}',200000,true,'system','system') "
        "ON CONFLICT (provider_spec_id, model_name) DO NOTHING;"
    )
    spec_id = _psql(
        f"SELECT id FROM model_specs WHERE provider_spec_id='{llm_provider_spec_id}' "
        f"AND model_name='{LLM_MODEL}';"
    )
    assert spec_id, "failed to seed model_spec"
    return spec_id


@pytest.fixture
def llm_model(
    alice_client: httpx.Client,
    llm_provider_spec_id: str,
    llm_model_spec_id: str,
) -> str:
    """Create a workspace-scoped provider_config + model_instance.

    Returns the model_instance UUID, usable directly as `model_id` on agent create.
    """
    pc = alice_client.post(
        "/v1/provider-configs/",
        json={
            "provider_spec_id": llm_provider_spec_id,
            "name": f"e2e-llm-{uuid.uuid4().hex[:6]}",
            "api_key": LLM_API_KEY,
            "endpoint_url": LLM_ENDPOINT,
        },
    ).raise_for_status().json()
    assert pc["endpoint_url"] == LLM_ENDPOINT, (
        "provider_config dropped endpoint_url — regression of the repo fix"
    )

    mi = alice_client.post(
        "/v1/model-instances/",
        json={
            "provider_config_id": pc["id"],
            "model_spec_id": llm_model_spec_id,
            "name": f"e2e-llm-{uuid.uuid4().hex[:6]}",
        },
    ).raise_for_status().json()
    return mi["id"]
