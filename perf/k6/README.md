# k6 API performance suite

Read-only load tests for the pages a user hits when opening the app:
workspaces, connections, explore/catalog, skills, triggers, tasks, inbox, plus
`/health` as the unauthenticated floor. Lives next to the routes it exercises
so a routing change (like the workspace-in-path move) and the script that
hits it land in the same PR.

## Running it

```bash
# load prod credentials into this shell only
set -a; . ~/.config/agentarea/ru.env; set +a

cd perf/k6
make smoke      # 1 VU, 1 iteration, every page once — correctness + single-request latency
make baseline   # ramps to 5 VUs over 3 minutes, 1-3s think time — the real baseline
```

Both write a markdown table to stdout and to `results/<scenario>-report.md`,
plus the full k6 JSON summary to `results/<scenario>-summary.json`. `results/`
is gitignored — it's local output, not something to commit.

Env vars, read from `__ENV`:

| var | default | notes |
|---|---|---|
| `AGENTAREA_TOKEN` | none | required; the suite refuses to start without it |
| `AGENTAREA_API_URL` | `https://api.agentarea.ru` | |
| `WORKSPACE` | `user` | workspace slug the workspace-scoped routes hit |

k6 does **not** read the process environment on its own — a var exported in
the shell is invisible to the script unless it's also forwarded with `-e`.
The `make` targets do this for you (they pick the vars up from `make`'s own
environment import and forward them); running k6 directly needs it spelled
out:

```bash
k6 run -e AGENTAREA_TOKEN="$AGENTAREA_TOKEN" -e AGENTAREA_API_URL="$AGENTAREA_API_URL" scenarios/smoke.js
```

## Safety rules

- **Read-only.** Every request is a GET. Nothing here creates, deletes, runs a
  task, or calls an MCP tool.
- **Gentle by default.** `baseline` tops out at 5 VUs for 3 minutes — sized
  for a small prod cluster (three 4-vCPU nodes, 2 API pods, 1 uvicorn worker
  each), not a load test.
- **`stress` is opt-in and never for prod.** It ramps to 50 VUs and refuses to
  run at all unless `ALLOW_STRESS=1` is set. Only ever point it at a
  staging/local target.
- **The token never touches disk or git.** Source `ru.env` into the shell
  each time; nothing in this directory reads or writes that file.

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

## Layout

```
perf/k6/
  lib/
    config.js      env vars, auth header, fail-fast if the token is missing
    http.js         get/getPublic/batchGet — tagging + checks in one place
    endpoints.js     NAMES + pages: what gets hit and how it's grouped
    thresholds.js    builds the threshold map from NAMES + pages
    summary.js       handleSummary: markdown table + JSON dump
  scenarios/
    smoke.js         1 VU, 1 iteration, every page
    baseline.js      ramping-vus, 5 VUs / 3 min, gentle
    stress.js        ramping-vus, 50 VUs — gated on ALLOW_STRESS=1, non-prod only
  Makefile
```
