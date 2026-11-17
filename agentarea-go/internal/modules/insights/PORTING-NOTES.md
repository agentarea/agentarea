# insights: porting notes

Python paths are relative to `agentarea-platform/`. Dossier: `.omc/research/go-migration/dossiers/insights.md`.

## Routes

Mounted: 8 of 9 operations in `api/openapi/insights` (the ninth, `GET /health`, is the serve root route).

- `GET /v1/analytics` (principal, `api/v1/analytics.py:31-48`).
- `GET /v1/workspaces/{workspace}/balance` (member, `api/v1/dashboard.py:752-782`).
- `GET /v1/workspaces/{workspace}/dashboard` (member, `dashboard.py:542-736`).
- `GET /v1/workspaces/{workspace}/agents/{agent_id}/overview` (member, `agent_overview.py:72-252`).
- `GET /v1/workspaces/{workspace}/settings` (member) and `PUT` (admin) (`dashboard.py:793-864`). PUT is a raw handler: it tells an absent body from `null`, and checks the admin before reading the body, as `requires_workspace_admin()` runs first.
- `GET /v1/workspaces/{workspace}/network/topology` (member, `network.py:125-545`).
- `GET /v1/workspaces/{workspace}/network/people-access` (admin, `network_people.py:54-145`).

`GET /` and `GET /health` are the serve edge's root routes (`internal/serve`), not this module's.

`POST /internal/analytics/signups` (`api/internal/analytics_signups.py`, Kratos's
after-registration hook, ADR-0047) is mounted raw by `handlers/signups.go`, outside `/v1` and the
spec: 404 without `AGENTAREA_ANALYTICS_SIGNUP_HOOK_KEY`, 401 when `Authorization` is not the key,
422 on a bad body, else 204.

## Analytics

`service/analytics_runtime.go` is `start_analytics`, `InstallationPulse` and the sign-up hook over
one `Sender` (`service/sender.go`, `analytics/sender.py`). Components: `analytics sender` in serve
and worker (start: the installation row and the NOTICE, hourly sends; stop: a last send), and
`installation pulse` in worker (hourly tick, `pg_try_advisory_xact_lock(4107726903118)`, due a day
after `last_pulse_at`). A start that fails is logged and leaves analytics off; it never fails the
process. Counters reach the sender through `kernel/analytics.Handle`, which app passes to runs
(`run_refused`: spend caps, billing refusals, the PRE_LLM entitlement deny) and connections
(`connector_check` at every verification verdict, `oauth_connect` through the connect flow); before the sender starts, or with analytics
off, nothing is counted.

The pulse reads each foreign table through its owner (decision 3a): a narrow `TenantCounter`
(`api/tenant_counts.go`, SQL in `store/tenant_counts.go`) in identity, runs, agents, connections,
catalog, models, streams and governance, counts keyed by their own ids and naming their Python
source. `service/pulse.go` composes them as `collect_pulse` did in one session: the size buckets,
the activation milestones, the median's rounding and every `custom` label are decided there. Test on
postgres: `app/pulse_db_test.go`.

Deviations:
- A collector batch over `http.RoundTripper` of the vendor destination; no transport fails the
  batch (logged, dropped) instead of reaching the internet unproxied.
- A sign-up hook with a bad key is refused before its body is read; FastAPI read and parsed the
  JSON first, so a malformed body without the key answered 422 rather than 401.
- `created_at` without an offset is read as UTC; pydantic read it in the process's local zone.
- The pulse reads the owners' tables over the read pool, outside the lock's transaction; Python
  read them in the locking session. The lock still decides who sends.

`oauth_connect` is counted by connections at Python's thirteen sites (see its notes).

## Reads from other modules

Insights reads other modules only through their `api` packages (`service/deps.go`, `Reads`). The reads it needed were added to the owners in new files:

- runs: `api/insights.go` (`SpendLedger`, `TaskBoard`), `store/queries/insights.sql`, `service/insights.go`, `insights_reads.go` (`Surface.SpendLedger`, `Surface.TaskBoard`).
- streams: `api/insights.go` (`TriggerBoard`), `service/insights.go`, `insights.go` (`Module.TriggerBoard`). Topology uses the existing `Triggers.ListTriggers`.
- connections: `api/insights.go` (`ConnectionBoard`), `store/queries/insights.sql`, `service/insights.go`, `insights.go`.
- agents: `api/network.go` (`Network`), `store/queries/network.sql`, `store/network.go`, `service/network.go`, `network.go`.
- governance: `api/spendcap.go` (`SpendCaps`, `CapRefused`), `service/spendcap.go`, `spendcap.go`.
- identity: `api/owners.go` (`WorkspaceOwners`), `service/owners.go`, `owners.go`.
- wallet `Wallets.Exhausted`, catalog `MCPSpecs.Get`, agents `Lookup.AgentExists` existed.

The dashboard and network models live in `service/` (`dashboard_model.go`, `network_model.go`): they carry `money.Decimal` and `wirejson.Object`, which rule 3 keeps out of `domain/`. `domain/` holds the cron preview (`schedule.go`) and the analytics and balance shapes.

## Wiring

Insights is built before runs, streams and wallet, so their reads come late: `app/modules.go` passes `Admin: e.Admin` in `insights.Deps` and calls `m.insights.Use(insightsPorts(d, m))` once every module exists; `app/insights_ports.go` builds the `Later` set (extension points nil-safe). `Serve().Mount` fails (`insights: Use was not called before serving`) if `Use` or `Admin` is missing.

## Fixed Python bugs

- The installation row's `created_at` and `updated_at` are the API process's naive local wall clock (`libs/common/agentarea_common/base/models.py:14-16`, `default=datetime.now`, written by `analytics/repository.py:18`). Go writes naive UTC. No client reads these columns. Test: `store/store_test.go` `TestGetOrCreateKeepsOneRowAndStoresUTC`.
- Topology swallowed every fetch failure (`network.py:186-241`, `logger.warning` then `[]`) and drew a partial graph as if the missing parts did not exist. Go returns 500. Test: `service/reads_test.go` `TestTopologyFailsLoudOnARead`; the dashboard likewise (`TestDashboardFailsLoudOnARead`).
- Topology took MCP icons only from specs in the caller's workspaces (`network.py:204-216`), so a platform-managed instance, whose spec lives in the platform workspace, had none. Go reads the spec through catalog `MCPSpecs.Get` with `PlatformBacked` set for a platform instance, once per spec. Test: `service/reads_test.go` `TestTopologyFindsThePlatformSpecIcon`.
- `PUT /settings` wrote, updated and deleted `policies` rows with no audit record, while the policy routes record every such change. Go records `governance_policy.create`/`update`/`delete` (audit failures are swallowed, as `@audited` does). Test: `governance/service/spendcap_test.go` `TestSpendCapSetUpdateAndClear`.

## Kept

- Balance returns 503 `balance is unavailable` on any non-HTTP source failure, and passes an HTTP error from the source through (`dashboard.py:764-778`). Test: `handlers/handlers_test.go` `TestBalanceSourceFailureIs503`.
- Balance returns JSON `null` with 200 when the deployment has no account_balance extension.
- Money renders as Python's `str(Decimal)`: ledger sums keep the column's 12 places (`"3.500000000000"`), an empty sum is `"0"`.
- Overview answers 404 `Agent not found` before any aggregate; a malformed `agent_id` is 422 `uuid_parsing`.
- People access: the membership graph failing is 503 `Workspace membership graph unavailable`; the cut to 100 people keeps the owner; `display_name` is always null and only the caller's own email is shown.
- The cron preview reads schedules as Temporal does (`_schedule_preview.py`): day of month and day of week must both match, a sixth field is the year, a wall time a DST change removes does not fire.

## Deviations

- Balance's source comes from the extension set. In a process without extensions it is nil.
- Config is read by the role's loader (`insights.LoadConfig`) and passed in `Deps.Config`; a bad value fails startup.
- `people-access` `directory_status` is always `available`: Go has no disabled-directory mode (the Python branch is unreachable with OpenFGA required).

## Tests

- `domain/schedule_test.go`: cron fields, names, `L`, year, dom-and-dow, DST gap, limits.
- `service/model_test.go`, `service/reads_test.go`: model math (quantize, percent of cap, projection, task cost, not-covered), topology edges, every route's service over fakes.
- `handlers/*_test.go`: status codes and exact bodies over httptest, PUT validation (missing, null, negative, not an amount, non-admin 403 before the body).
- Owner reads on postgres:18: `runs/service/insights_db_test.go`, `agents/service/network_db_test.go`, `connections/service/insights_db_test.go`, `streams/service/insights_test.go`; fakes for `governance/service/spendcap_test.go` and `identity/service/owners_test.go`.
- `test/suite/insights/`: dashboard, settings, overview, topology and people access over the stack.
