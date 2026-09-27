# k6 API performance suite

Two suites, sharing `lib/config.js` and `lib/http.js`:

- **`scenarios/*.js`** — read-only page-latency checks against any workspace.
  Good for "did this PR make things slower" on demand. See below.
- **`scenarios/journeys/*.js`** — full user journeys (browse *and* real
  create/read/update/delete flows, including a real LLM task run) against a
  dedicated `perf-k6` workspace, meant to run nightly from an in-cluster
  CronJob and feed Grafana. See "Journey suite" further down.

Both live next to the routes they exercise, so a routing change (like the
workspace-in-path move) and the script that hits it land in the same PR.

## Running the endpoint suite

```bash
# load prod credentials into this shell only
set -a; . ~/.config/agentarea/ru.env; set +a

cd perf/k6
WORKSPACE=<slug> make smoke      # 1 VU, 1 iteration, every page once — correctness + single-request latency
WORKSPACE=<slug> make baseline   # ramps to 5 VUs over 3 minutes, 1-3s think time — the real baseline
```

Both write a markdown table to stdout and to `results/<scenario>-report.md`,
plus the full k6 JSON summary to `results/<scenario>-summary.json`. `results/`
is gitignored — it's local output, not something to commit.

Env vars, read from `__ENV`:

| var | default | notes |
|---|---|---|
| `AGENTAREA_TOKEN` | none | required; the suite refuses to start without it |
| `AGENTAREA_API_URL` | `https://api.agentarea.ru` | |
| `WORKSPACE` | none | required; workspace slug the workspace-scoped routes hit — no default, so a stale/wrong slug fails loudly instead of quietly hitting the wrong workspace |

`k6 run` forwards the whole process environment into `__ENV` on its own
(`--include-system-env-vars`, on by default), so exporting `AGENTAREA_TOKEN`
and `AGENTAREA_API_URL` is enough — running `k6 run scenarios/smoke.js`
directly after sourcing `ru.env` works with no flags at all. **Don't** pass
either through `-e`: that puts the value in the process's argv, which any
local `ps`/`pgrep -fl` shows in plaintext to anyone with process-list access
on the machine. `-e` is for `WORKSPACE` only, a non-secret but required knob
(no default — see below) that the `make` targets pass explicitly:

```bash
k6 run -e WORKSPACE=<slug> scenarios/smoke.js
```

(`k6 inspect` does *not* forward the environment the same way `k6 run`
does — if you're validating a script with `k6 inspect`, pass
`-e AGENTAREA_TOKEN=dummy -e WORKSPACE=dummy` there, it's just for a
syntax/threshold check and never talks to a real API.)

## Safety rules

- **Read-only.** Every request is a GET. Nothing here creates, deletes, runs a
  task, or calls an MCP tool.
- **Gentle by default.** `baseline` tops out at 5 VUs for 3 minutes — sized
  for a small prod cluster (three 4-vCPU nodes, 2 API pods, 1 uvicorn worker
  each), not a load test.
- **`stress` is opt-in and never for prod.** It ramps to 50 VUs and refuses to
  run at all unless `ALLOW_STRESS=1` is set. Only ever point it at a
  staging/local target.
- **The token never touches disk, git, or argv.** Source `ru.env` into the
  shell each time; nothing in this directory reads or writes that file, and
  nothing passes it through `-e` (see "Running it" above for why).

## Thresholds

Encode the target, not today's reality — expect some to fail until the fixes
in this PR are deployed. Each scenario reports which ones failed.

- per-endpoint p95 < 500ms
- `/health` p95 < 150ms
- page-load p95 < 1s (a "page" is one or more parallel/sequential calls that
  make up a real page's data fetch — see `lib/endpoints.js`)
- `http_req_failed` < 1%, overall and per-endpoint

## Adding an endpoint

Everything endpoint-related lives in `lib/endpoints.js`:

1. Add a tag to `NAMES` — the route template (e.g. `GET /v1/workspaces/WS/whatever/`),
   not the literal URL, so metrics group by endpoint instead of fragmenting
   per query string. Keep it free of `{`, `}`, `,`, `:` — k6's threshold
   tag-filter parser treats those as syntax (see the comment in
   `lib/endpoints.js`).
2. Either add a call inside an existing page's `run()`, or push a new
   `{ name, run }` onto `pages`, wrapping the request(s) in `timedPage(...)`
   so it also gets a `page_load_duration` sample.
3. Thresholds and the report table pick it up automatically — both are built
   from `NAMES` / `pages` in `lib/thresholds.js` and `lib/summary.js`.

## Journey suite

`scenarios/journeys/*.js` — the full-app journey suite. Meant to run nightly
from an in-cluster CronJob against a dedicated workspace (slug `perf-k6`) and
push results to VictoriaMetrics for Grafana; can also be run by hand.

**Hard rule: write journeys (create/update/delete) only ever run against the
`perf-k6` workspace.** This is not configurable — `lib/journeys/guard.js`
hard-codes the workspace name and every write journey checks it before doing
anything. Point `WORKSPACE` at anything else and the browse journeys still
work (read-only, any workspace), but every write journey refuses with a loud
error instead of touching that workspace's data.

### Journeys

| journey | what it does |
|---|---|
| browse | one "page load" per real page: dashboard, agents, connections, explore (5 variants: default/sort/type-filter/search/deep-page), skills, tasks, inbox, triggers — plus `/health` and `/v1/workspaces`. Read-only, traced from the actual webapp source (sequential vs. parallel calls match what the page really does — see `lib/journeys/browse.js`'s header comment for the exact shape of each). |
| auth | authenticated no-op (`GET /v1/workspaces`) vs. `/health` — the gap is roughly what auth costs on every request. Read-only. |
| agent_lifecycle | create → read → update (attach a skill, and an MCP connection if a `k6-`-prefixed one already exists from `connection_lifecycle`) → delete. Write; perf-k6 only. |
| skill_lifecycle | create (plain markdown, no frontmatter needed) → read → delete. Write; perf-k6 only. |
| trigger_lifecycle | create a CRON trigger **disabled** (`enabled: false` at create — never enabled, never will be) → read → delete, plus its throwaway agent. Write; perf-k6 only. |
| connection_lifecycle | MCP instance from a real no-credential catalog entry when one qualifies (`spec.env_schema` empty, `spec.connection_type === "url"`), else a disposable spec of our own → list → delete; plus an OpenAPI connection against a public spec (Petstore by default) → delete. Write; perf-k6 only. |
| task_run | starts a real task (cheapest available model, prompt "Reply with exactly: OK") on a throwaway agent and measures `task_accepted` / `task_first_event` / `task_completed` (see "Metric contract"). The one journey with a real LLM cost — never in the random pick, always its own dedicated `shared-iterations` executor capped at `TASK_RUN_LIMIT` (default 3) total runs, independent of VU count. Write; perf-k6 only. |

### Profiles

| profile | script | shape |
|---|---|---|
| smoke | `scenarios/journeys/smoke.js` | 1 VU, 1 iteration, every journey once (including one `task_run`) — CI-safe against a local stack, as long as that stack's `WORKSPACE` is literally `perf-k6` |
| nightly | `scenarios/journeys/nightly.js` | two scenarios at once: `mixed` (ramping-vus, ≤5 VUs, ~7 min, weighted random pick — browse dominates, lifecycle journeys occasional) and `task_run` (`shared-iterations`, `TASK_RUN_LIMIT` runs total) |
| stress | `scenarios/journeys/stress.js` | ramping-vus to 50 — gated on `ALLOW_STRESS=1` **and** refuses outright if `AGENTAREA_API_URL` is the real prod host, no override |

```bash
set -a; . ~/.config/agentarea/perf.env; set +a   # AGENTAREA_TOKEN, AGENTAREA_API_URL, WORKSPACE=perf-k6
cd perf/k6
k6 run scenarios/journeys/smoke.js
TASK_RUN_LIMIT=3 k6 run --tag testid=manual-$(date +%F) -e TESTID=manual-$(date +%F) scenarios/journeys/nightly.js
```

Against any other workspace (e.g. `jamakase54`), the same commands run the
browse + auth journeys read-only and skip every write journey and `task_run`
with a log line, rather than failing the whole run.

### Janitor

`lib/journeys/janitor.js` runs in `setup()` (and again in `teardown()`) of
every journey-suite scenario, only when `WORKSPACE === "perf-k6"`: it lists
agents, skills, MCP instances, MCP specs, OpenAPI connections and triggers,
deletes anything whose `name` starts with `k6-`, and logs what it removed.
Every resource a write journey creates gets that prefix from
`lib/journeys/naming.js` (`k6-<TESTID>-<kind>-<vu>-<iter>-<timestamp>`) —
including one left behind by a run that crashed before its own inline
cleanup ran. It never touches anything without that prefix, and never runs
at all outside `perf-k6`.

### Metric contract

Stable on purpose — Grafana panels and alerts (perf-dashboards) key on these
names and tags. Run with `-o experimental-prometheus-rw` and
`K6_PROMETHEUS_RW_TREND_STATS=p(50),p(95),p(99),max` to get:

- Custom Trends (ms): `page_load` (tags `journey`=`browse`, `page`),
  `task_accepted`, `task_first_event`, `task_completed` (tag `journey`=`task_run`)
- Custom Counters: `page_visits` (tags `page`, `journey`), `task_runs` (tag `journey`)
- Built-ins, tagged on every request: `name`, `journey`, `step`, `kind`
  (`read`|`write`, set automatically by HTTP verb in `lib/http.js`), and
  `page` — present only on browse's page-load requests, absent elsewhere
- `testid` — set globally via `k6 run --tag testid=<value>` (and separately
  via `-e TESTID=<value>` so resource names carry it too — two different k6
  mechanisms, same value, both needed)

Resulting series, confirmed against k6 v2.3.0 source
(`internal/output/prometheusrw/remotewrite`) by perf-dashboards — note the
two things that aren't obvious from the metric names above: **Rate metrics
get a `_rate` suffix**, and **all time Trends (custom and built-in) convert
to seconds**, not the milliseconds this suite's own thresholds compare
against internally (k6 evaluates thresholds in its own native unit before
export; only the exported Prometheus values are in seconds):

- `k6_page_load_p95{journey,page,testid}` (seconds)
- `k6_task_accepted_p95{journey,testid}`, `k6_task_first_event_p95{...}`,
  `k6_task_completed_p95{...}` (seconds)
- `k6_http_req_duration_p95{name,journey,step,kind,page?,testid}` (seconds)
- `k6_page_visits_total{...}`, `k6_task_runs_total{...}`, `k6_http_reqs_total{...}` (counters)
- `k6_http_req_failed_rate{...}`, `k6_checks_rate{...}` (rates)

perf-dashboards' alerts use the same thresholds as the list below, taking
the max over each step's series.

SLO thresholds (`lib/journeys/thresholds.js`) — encode the target, expect
failures until things catch up:

- reads (`kind:read`) p95 < 500ms
- writes (`kind:write`) p95 < 1000ms
- `page_load` p95 < 1000ms
- `task_accepted` p95 < 1000ms
- `task_first_event` p95 < 5000ms
- `http_req_failed` rate < 1%, `checks` rate > 99%
- no threshold on `task_completed` — total LLM response time is inherently
  model-dependent, deliberately left unbounded

### Adding a journey

1. Write it in `lib/journeys/<name>.js` as `{ name, run }`. Read-only? Just
   call `lib/http.js`'s `get`/`getPublic`/`batchGet`. Writes anything? Call
   `assertWriteAllowed("<name>")` (from `guard.js`) first, add its `kind`
   string to `KINDS` in `naming.js`, name every created resource with
   `resourceName("<kind>")`, and clean up inline at the end — the janitor is
   a safety net for crashes, not a substitute for cleaning up.
2. Tag every request with `tag(journey, step, page?)` from `lib/journeys/tags.js`.
3. Wire it into `lib/journeys/index.js`: read-only browse pages go in
   `browse.js`'s `pages` array; a lifecycle-style write journey goes in
   `writeJourneys`; anything with a real external cost (like `task_run`)
   stays out of every pool and gets its own dedicated executor in
   `scenarios/journeys/*.js` instead.
4. If it deletes something, add its resource type to `janitor.js`'s sweep.
   Check whether its list endpoint returns a plain array or a
   `PaginatedResponse` (`.items`) first — they're mixed in this API. More
   importantly: check whether that list endpoint mixes in platform/catalog
   rows (several do — their own dependency comments say so) and, if the
   response model exposes no clean ownership field (several don't:
   `registry_item_id`/`is_builtin`/`workspace_id` exist on the domain model
   but aren't always serialized — checked this for MCP specs, see
   `ownedMcpSpec()` in `janitor.js`), find whatever field IS exposed that's
   true for what this suite creates and false for shared/catalog rows
   (`is_public` served that purpose for specs), and pass it as `sweep()`'s
   `extraFilter`. `isOurs()`'s regex is strict, not a prefix, precisely so
   this kind of accidental collision with a real catalog item can't happen —
   don't undo that by loosening it back to a prefix check.

## Layout

```
perf/k6/
  lib/
    config.js         env vars, auth header, fail-fast if the token or workspace is missing, TESTID
    http.js            get/getPublic/batchGet/postJson/patchJson/putJson/del/getWithTimeout —
                        tagging (incl. automatic kind:read|write) + checks in one place
    endpoints.js        NAMES + pages: the original endpoint suite's targets
    thresholds.js       builds the threshold map for the endpoint suite
    summary.js          handleSummary: markdown table + JSON dump (endpoint suite only)
    journeys/
      guard.js           hard-coded perf-k6 workspace check for every write journey
      naming.js           k6-<testid>-<kind>-... resource names + isOurs()'s strict ownership regex
      tags.js              {journey, step, page?} tag builder
      metrics.js           page_load/page_visits/task_* custom metrics
      thresholds.js        SLO thresholds for the journey suite
      janitor.js            sweeps k6-prefixed leftovers at setup()/teardown()
      browse.js             read-only page-load journeys
      auth.js                token-validation-cost journey
      agent_lifecycle.js     create/read/update/delete an agent
      skill_lifecycle.js     create/read/delete a skill
      trigger_lifecycle.js    create (disabled)/read/delete a cron trigger
      connection_lifecycle.js MCP instance + OpenAPI connection lifecycles
      task_run.js             the real-LLM-call journey
      index.js                assembles the pools every scenario reads from
  scenarios/
    smoke.js         endpoint suite: 1 VU, 1 iteration, every page once
    baseline.js      endpoint suite: ramping-vus, 5 VUs / 3 min, gentle
    stress.js        endpoint suite: ramping-vus, 50 VUs — gated on ALLOW_STRESS=1, non-prod only
    journeys/
      smoke.js         journey suite: 1 VU, 1 iteration, every journey once
      nightly.js       journey suite: mixed ramping-vus + a capped task_run executor
      stress.js        journey suite: ramping-vus to 50 — gated + refuses a prod URL outright
  Makefile
```
