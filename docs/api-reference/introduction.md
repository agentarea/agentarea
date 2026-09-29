---
title: API reference
type: reference
description: "Base URL, authentication, workspace scoping, and pagination for the AgentArea REST API."
last_updated: 2026-09-10
---

Every endpoint below is generated from the OpenAPI specification the API serves
at `/openapi.json`, so it matches the running build rather than a hand-written
table. A local stack also exposes an interactive copy at
`http://localhost:8000/docs`.

## Base URL

| Deployment | Base URL |
|---|---|
| Local development | `http://localhost:8000` |
| Self-hosted | The public URL you configured for the API — see [networking](/self-host/networking) |

All platform endpoints are under `/v1`.

## Authentication

Send a bearer token on every `/v1` request:

```bash
curl -s "$AGENTAREA_URL/v1/workspaces" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

<Warning>
Requests without a valid token are rejected with `401`. There is no anonymous
read access to `/v1`, including on endpoints that look public.
</Warning>

## Workspace scoping

Authentication and workspace selection are two separate steps. A token
resolves to a user, who has no workspace yet; the workspace comes from the
request itself, never from a header and never from a default. Every
workspace-scoped endpoint below carries the workspace as a slug in the path:

```bash
curl -s "$AGENTAREA_URL/v1/workspaces/$WORKSPACE/agents/" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

`GET /v1/workspaces` lists the workspaces the token can reach — including the
user's personal one, provisioned on first call — and each entry's `slug` is
what goes in `$WORKSPACE`. There is no implicit "current workspace" and no
personal-workspace fallback: a request that omits the path segment on a
workspace-scoped endpoint is rejected, and a slug the token cannot reach is
refused with `403`, the same response as a slug that does not exist. An API
key is bound to the one workspace it was issued for; naming any other
workspace in the path also gets `403`.

A handful of endpoints are not workspace-scoped in the path because they
address one specific entity instead, and the workspace is resolved from that
entity: the A2A surface (`/v1/agents/{agent_id}/a2a/*` and its
`.well-known` documents), the MCP instance proxy (`/v1/mcp/{instance_id}/mcp`),
and inbound webhooks (`/webhooks/{webhook_id}`). `GET/POST /v1/workspaces`
itself and invitation preview/accept are the only endpoints with no workspace
context at all.

Every list endpoint returns only what the selected workspace can see, and
every write lands in it — there is no global scope and no cross-workspace
query. See [workspaces, projects, and resources](/concepts/workspaces-projects-resources)
for the model this enforces.

## Errors

Failures return a JSON body with a machine-readable code. The meanings, and
which ones are safe to retry, are in [errors](/reference/errors).

## Related

<Columns cols={2}>
  <Card title="Start a task" icon="list-check" href="/guides/tasks/start-a-task">
    The most common first call, end to end.
  </Card>
  <Card title="Errors" icon="book" href="/reference/errors">
    What each failure code means.
  </Card>
  <Card title="Limits" icon="book" href="/reference/limits">
    Budgets, quotas, and the ceilings requests are checked against.
  </Card>
  <Card title="Authorization model" icon="book" href="/reference/authorization-model">
    The relations behind every permission check.
  </Card>
</Columns>
