---
title: API overview
type: reference
summary: Authentication, workspace scoping, pagination, errors, and streaming for the AgentArea REST API.
prerequisites: []
related:
  - /getting-started
  - /mcp-access-tokens
  - /security
last_updated: 2026-07-29
---

# API overview

AgentArea exposes a REST API built with FastAPI. Every endpoint, parameter, and
schema is generated from the OpenAPI specification and listed under **API
Endpoints** in the sidebar — 176 paths across 233 schemas. This page covers the
conventions that apply across all of them.

The specification is the source of truth. It is exported from the running
backend and CI fails if it drifts, so the endpoint pages cannot go stale
independently of the code.

## Interactive documentation

When running AgentArea locally:

| Surface | URL |
|---|---|
| Swagger UI | `http://localhost:8000/docs` |
| ReDoc | `http://localhost:8000/redoc` |
| Raw specification | `http://localhost:8000/openapi.json` |

## Authentication

All endpoints require a JWT bearer token. Identity is managed by Ory Kratos;
machine clients use API keys exchanged for a token.

```bash
curl http://localhost:8000/v1/agents \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

Requests without a valid token are rejected at the edge, before any handler
runs. See [Security](/security) for the authorization model and
[MCP access tokens](/mcp-access-tokens) for machine credentials.

## Workspace scoping

Every resource is scoped to a workspace, and the workspace is derived from the
authentication context — you never pass it explicitly. A token issued for one
workspace cannot read or write another's resources, and this is enforced in the
repository layer rather than per endpoint.

## Pagination

List endpoints paginate, but two schemes are in use depending on the endpoint:

| Scheme | Parameters | Where |
|---|---|---|
| Offset | `limit`, `offset` | most list endpoints |
| Page | `page`, `page_size` | some newer endpoints |

Check the endpoint page for which parameters it accepts — they are not
interchangeable. This inconsistency is known and not yet reconciled.

Many list endpoints also accept filters such as `status`, `is_active`, `search`
and `tag`. The generated endpoint pages list the exact set per operation.

## Errors

Validation failures return `422` with a list of field-level errors:

```json
{
  "detail": [
    {
      "type": "missing",
      "loc": ["body", "name"],
      "msg": "Field required",
      "input": {}
    }
  ]
}
```

Other failures return the relevant status code with `detail` as a string
message. `detail` is therefore either a string or an array depending on the
error class — branch on the status code, not on the shape.

## Streaming

Task execution emits events over Server-Sent Events. Events belong to a task
under its agent, so the stream path is nested:

```bash
curl -N "http://localhost:8000/v1/agents/$AGENT_ID/tasks/$TASK_ID/events/stream" \
  -H "Authorization: Bearer $AGENTAREA_TOKEN"
```

There is also a non-streaming `.../events` endpoint that returns the events
recorded so far. Both are listed under **API Endpoints**.

## Base URL

The specification does not declare a `servers` block, so the interactive
playground has no default host. Prefix requests with your own deployment's
origin — `http://localhost:8000` for the local development stack.
