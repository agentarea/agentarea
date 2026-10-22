---
title: Usage analytics
type: reference
description: "What anonymous usage statistics an AgentArea installation sends to AgentArea, and how to turn them off with one variable."
prerequisites:
  - /self-host/configuration
related:
  - /self-host/observability
  - /self-host/configuration
  - /self-host/docker-compose
  - /self-host/kubernetes
last_updated: 2026-10-14
---

Every AgentArea installation sends anonymous usage statistics to AgentArea, and
`AGENTAREA_ANALYTICS_ENABLED=false` stops all of it.

## Synopsis

Usage analytics is not telemetry and not OpenTelemetry. OpenTelemetry traces and
Prometheus metrics (`AGENTAREA_OTEL_*`, `AGENTAREA_METRICS_*`) go to your own
monitoring; see [observability](/self-host/observability). Usage analytics goes to
AgentArea, at `https://analytics.agentarea.ai`, and answers product questions:
how many installations reach a first successful run, which connectors fail to
connect, which features are used.

Three sources send it. None of them sends an event per action.

| Source | Runs in | What | Cadence |
|---|---|---|---|
| Pulse | worker | counts computed from the database | once a day per installation |
| Failure counters | API and worker, in memory | attempts that leave no row: OAuth connects, connector checks, refused runs | sent hourly |
| Page views | webapp, server side | the route pattern of each page rendered | sent hourly |

The API and the worker each log one line at start while analytics is on:

```text
Anonymous usage analytics is on (what is sent: https://docs.agentarea.ai/self-host/analytics). Turn it off with AGENTAREA_ANALYTICS_ENABLED=false.
```

The webapp reads no variable of its own. It asks the API with
`GET /v1/analytics`, which returns `{enabled, install_id, collector_url,
collector_key, edition}`, so the backend and the UI cannot disagree.

Analytics never stops AgentArea. If it cannot start, for example because the
database is not reachable at that moment, the process logs an error and runs with
analytics off until it restarts. If the collector does not accept events, the
events are dropped: the first failure is logged as a warning with its traceback,
a continuing outage at most once a day with the number of events dropped, and the
recovery once.

## Parameters

| Variable | Helm value | Default | Description |
|---|---|---|---|
| `AGENTAREA_ANALYTICS_ENABLED` | `global.analytics.enabled` | `true` | `false` sends nothing from the API, the worker or the webapp |

Set it on the backend and the worker. The chart and `docker-compose.yaml` set both
from the one value. `docker-compose.dev.yaml` defaults it to `false`, and the CI
overlay `docker-compose.ci.yaml` sets it to `false`.

## Identifiers

Each installation has one anonymous id, `install_id`: a random 32-character hex
string created on first use and stored in the single-row `installation` table.
It identifies the installation and nothing else.

Where a source needs a user or workspace id, it sends
`hmac_sha256(install_id, id)` truncated to 16 hex characters. Page views carry
one as `user_id`, made from the signed-in person's identity id. The value is keyed
by `install_id`, and `install_id` travels with every event: the same person is
countable inside one installation, but the value does not reveal the identity id
and does not match the same person in another installation.

Every event carries this context:

| Field | Value |
|---|---|
| `install_id` | the installation's anonymous id |
| `version` | the AgentArea version, as `/health` reports it |
| `edition` | `AGENTAREA_EDITION` |
| `surface` | `webapp`, on page views only |

## What is sent

### Pulse: event `installation_pulse`

| Group | Fields |
|---|---|
| Installation | `install_id`, `version`, `edition`, install age in days |
| Volume | workspaces and users (total, active 7 days / 30 days); agents (total, created in 24 hours); runs in 24 hours by `status` and origin (`user`, `trigger`, `agent`, `api`); failed runs in 24 hours by failure reason; median run duration |
| Adoption | connectors by kind (`mcp`, `openapi`), by catalog slug or `custom`, by auth type, by verification status (MCP connectors); active triggers by type; skills (catalog slug or `custom`); installed bundles (catalog slug or `custom`); policies; registered clients by kind; LLM providers by provider type; workspace size buckets (1, 2–5, 6+) |
| Activation | personal workspaces created in the last 7 days, and how many of them have an agent and a successful run within 1 and within 7 days of creation |

A catalog slug is sent only for an item of AgentArea's own catalog: a registry
whose source is `https://agentarea-mcp-registry.s3.amazonaws.com/registry/` (the
registries the chart, Docker Compose and `agentarea-api reconcile` set up) or a
`builtin://` registry created by a migration. A connector, skill or bundle from
a registry you added, or from no registry, is sent as `custom`.

A workspace or user is active in a window when it created a run in it. The
platform workspace, which holds what the operator supplies to every workspace, is
not counted. A failure reason that is not a short code is sent as `other`.

The `install_id`, `version` and `edition` travel in the event context. The
properties look like this:

```json
{
  "install_age_days": 42,
  "workspaces": {"total": 12, "active_7d": 5, "active_30d": 8},
  "users": {"total": 20, "active_7d": 6, "active_30d": 11},
  "agents": {"total": 31, "created_24h": 2},
  "runs_24h": {
    "by_status": {"completed": 40, "failed": 3},
    "by_origin": {"user": 25, "trigger": 15, "agent": 2, "api": 1},
    "failed_by_reason": {"no_credits": 1, "unknown": 2},
    "median_duration_seconds": 12.5
  },
  "connectors": {
    "by_kind": {"mcp": 5, "openapi": 2},
    "by_catalog": {"io.github.github/github-mcp-server": 2, "custom": 5},
    "by_auth_type": {"oauth2": 3, "api_key": 1, "none": 3},
    "by_verification_status": {"succeeded": 4, "failed": 1}
  },
  "triggers_active": {"cron": 3, "stream": 1},
  "skills": {"anthropics/pdf": 1, "custom": 2},
  "bundles": {"custom": 1},
  "policies": 4,
  "clients": {"harness": 2},
  "llm_providers": {"openai": 2, "anthropic": 1},
  "workspace_sizes": {"1": 10, "2-5": 2, "6+": 0},
  "activation_7d": {
    "personal_workspaces": 5,
    "with_agent": 3,
    "succeeded_within_1d": 2,
    "succeeded_within_7d": 3
  }
}
```

### Failure counters: event `counters`

Each entry is `{name, labels, count}`, counted since the last send. A label value
that is not a short code is sent as `other`. One send holds at most 1,000
distinct name and label combinations; past that, a count is added to its name
under the single label `{"overflow": "true"}`.

| Name | Labels |
|---|---|
| `oauth_connect` | `provider`, `outcome` (`started`, `succeeded`, `failed:<code>`) |
| `connector_check` | `kind` (`mcp`), `outcome` (`ok` or an error code) |
| `run_refused` | `reason` (`budget_cap`, `no_credits`, `policy_denied`, `other`) |

`provider` of `oauth_connect` is one of:

- the issuer's host name, only when it is one of the public providers
  `accounts.google.com`, `api.notion.com`, `auth.atlassian.com`, `github.com`,
  `gitlab.com`, `linear.app`, `login.microsoftonline.com`,
  `login.salesforce.com`, `oauth.yandex.ru`, `slack.com`, `www.canva.com`,
  `www.figma.com`, and is also configured as a platform OAuth app in
  `AGENTAREA_MCP_OAUTH_APPS`
- `custom`: any other authorization server, your own included, even when it is a
  platform OAuth app
- `unknown`: the flow failed before its connection was known, such as an expired
  state, a sign-in the provider refused, or a workspace deleted meanwhile

The `<code>` of `failed:<code>` is one of AgentArea's own codes
(`invalid_state`, `missing_code`, `workspace_gone`, `connection_gone`,
`not_authorizable`, `dcr_failed`, `oauth_app_required`, `token_exchange_failed`,
`no_access_token`) or an error code of RFC 6749 §4.1.2.1 and §5.2 that the
provider sent back (`invalid_request`, `unauthorized_client`, `access_denied`,
`unsupported_response_type`, `invalid_scope`, `server_error`,
`temporarily_unavailable`, `invalid_client`, `invalid_grant`,
`unsupported_grant_type`). Any other error the provider sends is `other`.

`reason` of `run_refused` is `budget_cap` for a workspace or agent spend cap,
`no_credits` for a balance that ran out, `policy_denied` for a governance gate,
and `other` for any other refusal, such as a model with no price. A refusal
because billing could not answer is not counted.

### Page views: event `page_viewed`

| Field | Value |
|---|---|
| `user_id` | the signed-in person's pseudonym, as described in [Identifiers](#identifiers) |
| `properties.route` | the route pattern, such as `/w/*/connections/create/*`; never an id or a query value |
| `context` | `install_id`, `version`, `edition`, `surface: "webapp"` |

Prefetches are not counted, and the same person on the same path counts once per
30 minutes.

## Never sent

- names, emails, task text, prompts, model output, file contents
- names of resources you create: a custom connector is sent as `custom`
- ids from a registry you added, and host names of authorization servers other than the public providers listed above: both are sent as `custom`
- secrets
- URLs

The collector sees the address a request comes from, as any HTTP server does,
and does not store it.

## Example

Turn analytics off.

<Tabs>
  <Tab title="Docker Compose">
    In `.env`:

    ```bash
    AGENTAREA_ANALYTICS_ENABLED=false
    ```

    Then recreate the containers: `docker compose up -d`.
  </Tab>
  <Tab title="Kubernetes">
    In your values file:

    ```yaml
    global:
      analytics:
        enabled: false
    ```

    Then `helm upgrade` the release.
  </Tab>
</Tabs>

Check that it is off: the start-up line above is absent from the API and worker
logs, and `GET /v1/analytics` returns:

```json
{"enabled": false, "install_id": null, "collector_url": null, "collector_key": null, "edition": null}
```

## Related

<Columns cols={2}>
  <Card title="Collect logs and traces" icon="server" href="/self-host/observability">
    Your own monitoring: JSON logs, OpenTelemetry, Prometheus
  </Card>
  <Card title="Configuration" icon="server" href="/self-host/configuration">
    Every environment variable and the Helm value that sets it
  </Card>
  <Card title="Deploy with Docker Compose" icon="server" href="/self-host/docker-compose">
    Run the full platform on one host
  </Card>
  <Card title="Deploy on Kubernetes with Helm" icon="server" href="/self-host/kubernetes">
    Install the agentarea Helm chart
  </Card>
</Columns>
