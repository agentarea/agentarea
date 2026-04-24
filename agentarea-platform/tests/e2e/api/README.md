# Local API e2e tests

Live tests against the running dev stack. Each test provisions ephemeral
Kratos identities via admin API, exchanges session tokens for `agentarea_jwt`,
and tears the identities down on teardown.

## Prereqs

`docker compose up` with:

- Kratos admin at `http://localhost:4434`
- Kratos public at `http://localhost:4433`
- Backend at `http://localhost:8000`
- Kratos `tokenize_as: agentarea_jwt` template configured (already set in
  `config/auth/kratos/kratos.yml`)

## Run

```
uv run pytest -m integration tests/e2e/api/ -v
```

With parallelism (recommended for the fuzz layer):

```
uv run pytest -m integration tests/e2e/api/ -n 4
```

Override endpoints:

```
KRATOS_ADMIN_URL=http://... KRATOS_PUBLIC_URL=http://... API_URL=http://... \
  uv run pytest -m integration tests/e2e/api/
```

## Layers

1. **Handwritten explicit tests** — strong business assertions:
   - `test_smoke_get.py` — every safe GET must not 5xx, no-auth = 401
   - `test_workspace_isolation.py` — Alice cannot see or touch Bob's resources
   - `test_api_key_lifecycle.py` — create / use / revoke / scope

2. **OpenAPI-driven fuzz** (`test_openapi_fuzz.py`) — [schemathesis](https://schemathesis.readthedocs.io/)
   walks every route in `/openapi.json`, generates payloads, asserts the
   server never returns 5xx. Catches regressions we would not write by hand.
   Configured for "smoke" strictness only (5xx detection). Tightening checks
   (response-schema conformance, undocumented-status, negative-data) is a
   future cleanup per endpoint.

## Adding new tests

- Put critical flows in hand-written files with explicit asserts.
- Let the fuzz layer cover "did I break anything broadly" for free.
- Use the `alice_client` / `bob_client` fixtures for isolation scenarios;
  use `user_factory("label")` when you need more than two.

## Fixtures (`conftest.py`)

- `kratos_admin` / `kratos_public` — session-scoped httpx clients
- `user_factory` — mint an ephemeral user, auto-cleanup
- `alice`, `bob` — convenience wrappers returning `TestUser(identity_id, email, session_token, jwt)`
- `alice_client`, `bob_client` — httpx clients pre-authed with each user's JWT
- `anon_client` — unauthenticated baseline
