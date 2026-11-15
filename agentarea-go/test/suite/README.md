# Behaviour suite

One set of Go tests that drives the HTTP API of `agentarea serve` as a black
box (phase 1 step 7). The Python backend is the behaviour spec, with its bugs
fixed (decision 9): a test pins the fixed behaviour. Python never runs in this
stack.

## Layout and build tag

- `test/suite/<module>/*_test.go`, one package per module, written by the test
  author, not the porter.
- `test/suite/harness`: clients, principals, per-test workspaces, JSON
  matchers, SSE and WebSocket readers, polling. Suites import only the harness
  and the standard library, never `internal/`: they see the backend as a black
  box.
- Build tag `suite` on every file but `harness/doc.go`, so `make check` never
  needs a running stack. `go test -tags suite ./test/suite/harness/` runs the
  harness's own tests (no stack needed).
- `deploy/suite/`: the isolated stack (`compose.yaml`, `stack.sh`).

## The stack

`deploy/suite/stack.sh` runs the infrastructure services of
`docker-compose.dev.yaml` with `deploy/suite/compose.yaml` on top as compose
project `aa-suite`: its own volumes, host ports in 57000-57999, nothing
published on the dev ports, so it runs beside `make up-dev`. Every service is
`pull_policy: never` and the stack starts with `--no-build`: it uses only
local images.

Started: Postgres, Kratos, Hydra, OpenFGA, Valkey, RustFS, Temporal, mailpit.
The database gets the goose baseline (`schema.Migrate`, through
`go run ./tools/schemacheck apply`). Then `agentarea` is built from this module
and `agentarea serve` (`:57900`) and `agentarea worker` run on the host with
`.state/go.env`; their logs are `.state/serve.log` and `.state/worker.log`.
Until a module is ported, serve answers its routes 404 and its suite is red.
Not started: mcp-manager, sandbox executor, event-service, the catalog
reconcile (it fetches from the internet); a suite that needs one adds it to
`services` in `stack.sh`.

`stack.sh up` writes `deploy/suite/.state/` (gitignored): fresh secrets in
`suite.env`, a Kratos config copied from `config/auth/kratos` with its own
signing key, and `go.env`. `stack.sh down` stops serve and worker and removes
containers, volumes and `.state`.

| Port | Service |
|---|---|
| 57900 | `agentarea serve` (host) |
| 57433 / 57434 | Kratos public / admin |
| 57444 / 57445 | Hydra public / admin |
| 57432 | Postgres (`postgres`, password in `.state/suite.env`) |
| 57379 | Valkey |
| 57088 | OpenFGA HTTP |
| 57233 | Temporal |
| 57090 | RustFS S3 |

## Running

```sh
cd agentarea-go
deploy/suite/stack.sh up                         # about a minute from cold
deploy/suite/stack.sh test                       # every suite
deploy/suite/stack.sh test ./test/suite/projects/ -run Nest -v
deploy/suite/stack.sh down
```

`stack.sh test [go test args]` is `go test -tags suite -count=1` with the
environment below. To set it yourself: `eval "$(deploy/suite/stack.sh env)"`.

## Environment

| Variable | Meaning |
|---|---|
| `BASE_URL` | Origin of the backend under test, e.g. `http://localhost:57900`. |
| `SUITE_KRATOS_PUBLIC_URL` | Kratos public API, for the login flow. |
| `SUITE_KRATOS_ADMIN_URL` | Kratos admin API, to create and delete identities. |

All three are required; a suite package's `TestMain` (`harness.Main`) exits 2
without them. These are test-harness names, read under `/test/` only, which
the env-name guard treats as fixtures.

## Principals and isolation

The harness signs people in the way `agentarea-platform/tests/e2e/api/conftest.py`
does: a Kratos identity created through the admin API, the password login API
flow, then `/sessions/whoami?tokenize_as=agentarea_jwt`. The JWT (30-minute
TTL) is re-issued from the session after 15 minutes.

- `harness.People(t)`: `Owner`, `Member`, `Outsider`, minted once per test
  process and deleted from Kratos when it exits.
- `harness.NewWorkspace(t)`: a shared workspace made for this test. The owner
  creates it, invites the member, the member accepts; the outsider gets a
  workspace of its own. `w.Owner`, `w.Member`, `w.Outsider`, `w.Anonymous` are
  the clients; `w.Path("/projects/")` and `w.OutsiderPath(...)` build routes.
  Tests never share rows, so they need no cleanup and may run in parallel.
- `w.APIKey(t)`: a workspace API key (`aat_`) created by the owner.
  `w.AgentKey(t, agentID)`: a key bound to one agent (the A2A credential).
  `harness.Bearer(t, name, token)`: any other token.
- Cross-workspace cases use the outsider: in its own workspace a foreign id is
  404; naming the other workspace in the path is 403.

## What a test asserts

- Status (`Response.Expect`), `Content-Type` (`Response.ContentType`), and the
  body as a JSON value (`Response.Match(want)`). Objects compare by their full
  key set: a missing or extra field fails. Arrays compare in order;
  `harness.Unordered` and `harness.Contains` when the backend promises no order.
- Fields that differ per run are matched by shape, never dropped:
  `AnyUUID`, `AnyString`, `AnyNumber`, `AnyTimestamp`, `Pattern(re)`, `Any`.
- Error bodies: `harness.Problem(status, code, detail)` is the RFC 9457 body
  `agentarea_common/exceptions/handlers.py` writes; a 422 adds `errors`.
- Redirects are returned, not followed (FastAPI's 307 to the slashed path is
  behaviour).
- SSE: `c.Stream(t, path, within)` then `Next`, `Take(n, d)`, `Until(d, match)`.
  WebSocket: `c.DialWS(t, path, header)` then `ReadJSON`, `WriteJSON`, `Read`
  (close code in `CloseCode`); a refused upgrade is a `*WSHandshakeError` from
  `TryDialWS`.
- Asynchronous effects: `harness.Eventually(t, within, cond)` and
  `harness.Never(t, period, cond)`.

## Adding a suite

1. `test/suite/<module>/<module>_test.go` with `//go:build suite` and
   `func TestMain(m *testing.M) { harness.Main(m) }`.
2. Read the module's dossier (`.omc/research/go-migration/dossiers/<module>.md`):
   sections 2 (routes), 10 (oddities) and 11 (what tests pin) say what to cover.
3. Each test starts with `w := harness.NewWorkspace(t)` and creates what it
   needs through the API.
4. Take the expected behaviour from the Python code and the dossier. Prove each
   assertion can fail (change an expected value, see it red) before keeping it.
