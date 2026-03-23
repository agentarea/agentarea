# OpenAPI Connections

**Date:** 2026-03-16
**Status:** Draft
**Scope:** Add ability to register OpenAPI services, parse specs, and store discovered tools

## Context

AgentArea manages MCP server connections via `mcp_server_instances`. We want to support OpenAPI-based REST APIs alongside MCP, without unifying them into a single table — they have fundamentally different lifecycles (MCP has start/stop/health via Go manager + Temporal; OpenAPI is always-on config + HTTP).

## Decisions

- **Separate table** from MCP — `openapi_connections` with its own model, repository, service, and API route
- **Same auth pattern** — reuse `mcp_auth_configs` for auth config (API key, bearer, OAuth2)
- **Same credential flow** — deterministic secret key via `BaseSecretManager`
- **Same tool shape** — `available_tools` stores `[{name, description, inputSchema}]`, same object format as MCP. Storage differs: dedicated column here vs nested in MCP's `json_spec`
- **No agent execution yet** — tools are discoverable but agents can't invoke them in this phase
- **No registry integration** — OpenAPI specs are manually added, not synced from catalogs

## Data Model

### `openapi_connections` table

| Column | Type | Notes |
|---|---|---|
| id | UUID | PK (BaseModel) |
| workspace_id | str | WorkspaceScopedMixin |
| created_by | str | WorkspaceScopedMixin |
| name | str(255) | NOT NULL |
| description | text | nullable |
| spec_url | text | nullable — URL to fetch OpenAPI spec from |
| spec_content | JSON | nullable — stored/uploaded OpenAPI spec |
| base_url | str(500) | NOT NULL — API base URL for requests |
| auth_config_id | UUID FK | -> mcp_auth_configs.id, nullable, ondelete SET NULL |
| available_tools | JSON | `[{name, description, inputSchema}]` |
| status | str(50) | `active` / `unreachable`, default `active` |
| created_at | datetime | BaseModel |
| updated_at | datetime | BaseModel |

No lifecycle management (no start/stop). Status is informational only.

Both `spec_url` and `spec_content` are nullable — a connection can exist with just `base_url` and have tools discovered later via the `/discover-tools` endpoint.

## OpenAPI Spec Parsing

### Tool extraction from OpenAPI spec

For each `paths.{path}.{method}` operation:

1. **Name**: `operationId` if present, otherwise generate from `{method}_{path_segments}` (e.g. `GET /users/{id}/orders` -> `get_users_id_orders`)
2. **Description**: operation `summary` or `description`
3. **Input schema**: merge path parameters, query parameters, and request body into a single JSON Schema object
   - Path params: required string properties
   - Query params: optional properties with types from spec
   - Request body: nested under `body` property if present

### Example

OpenAPI operation:
```yaml
/users/{user_id}/orders:
  get:
    operationId: listUserOrders
    summary: List orders for a user
    parameters:
      - name: user_id
        in: path
        required: true
        schema: { type: string }
      - name: page
        in: query
        schema: { type: integer }
```

Becomes tool:
```json
{
  "name": "listUserOrders",
  "description": "List orders for a user",
  "inputSchema": {
    "type": "object",
    "properties": {
      "user_id": { "type": "string" },
      "page": { "type": "integer" }
    },
    "required": ["user_id"]
  }
}
```

## API Endpoints

### Route: `/v1/openapi-connections/`

| Method | Path | Description |
|---|---|---|
| POST | `/` | Create connection (with spec_url or spec_content + base_url) |
| GET | `/` | List all connections |
| GET | `/{id}` | Get connection with available_tools |
| PATCH | `/{id}` | Update connection |
| DELETE | `/{id}` | Delete connection |
| POST | `/{id}/discover-tools` | Fetch/parse spec, store available_tools |
| POST | `/{id}/test` | Health check request to base_url |

### Create request

```json
{
  "name": "Stripe API",
  "description": "Payment processing",
  "base_url": "https://api.stripe.com",
  "spec_url": "https://raw.githubusercontent.com/stripe/openapi/master/openapi/spec3.json",
  "auth_config_id": "uuid-of-existing-auth-config"
}
```

Or with uploaded spec:

```json
{
  "name": "Internal API",
  "base_url": "https://internal.example.com",
  "spec_content": { "openapi": "3.0.0", "paths": { ... } }
}
```

### Discover-tools response

```json
{
  "connection_id": "uuid",
  "tools_discovered": 42,
  "tools": [
    { "name": "listUsers", "description": "..." },
    { "name": "createOrder", "description": "..." }
  ]
}
```

## File Structure

```
libs/openapi/
  agentarea_openapi/
    __init__.py
    domain/
      models.py              # OpenAPIConnection SQLAlchemy model
    infrastructure/
      repository.py          # CRUD repository
    application/
      service.py             # Business logic + discover_tools
      spec_parser.py         # OpenAPI spec -> tool definitions

apps/api/agentarea_api/api/v1/
  openapi_connections.py     # FastAPI router
```

New library `agentarea_openapi` in the `libs/` workspace, following the same pattern as `agentarea_mcp`. Requires `pyproject.toml` and registration in the platform's `uv` workspace. Alembic migration in `apps/api/` for the new table.

### Error handling for discover-tools

- Spec URL unreachable: return 400 with fetch error message
- Invalid OpenAPI spec (not parseable): return 400 with parse error
- `$ref` resolution: use a library (e.g. `openapi-spec-validator` or `prance`) to resolve `$ref` references before extracting operations
- Supports OpenAPI 3.x only; return 400 for Swagger 2.0 specs with a message suggesting conversion

## Auth & Credentials

Reuses existing `mcp_auth_configs` table and `MCPAuthService`. The `auth_config_id` FK on `openapi_connections` points to the same auth configs used by MCP instances.

Credential flow:
- Auth config credentials stored in secret store via `mcp_auth_cred:{config_id}`
- When agent execution is added later, `MCPAuthService.get_auth_headers(config)` returns headers to inject into HTTP requests

Note: `MCPAuthService.delete()` checks for linked instances before deletion. This check must be extended to also query `openapi_connections` for the `auth_config_id`, or auth configs used by OpenAPI connections could be deleted.

## Out of Scope

- Agent execution of OpenAPI tools (`OpenAPITool.execute()`)
- Agent config integration (`{"type": "openapi", ...}` in agent tools)
- Registry/catalog sync for OpenAPI specs
- OpenAPI spec validation beyond basic parsing
- Webhook/callback support from OpenAPI specs
- GraphQL or other API protocol support

## Future Work

1. **Agent execution** — `OpenAPIToolFactory` + `OpenAPITool` that maps tool calls to HTTP requests with auth injection
2. **Agent config** — `{"type": "openapi", "name": "stripe-api", "settings": {"allowed_tools": [...]}}` in agent tools JSON
3. **Registry simplification** — delete `registries`/`registry_items`, add source metadata to `mcp_servers`/`skills` directly, sync from config (Helm values/env vars)
4. **Unified credential pattern** — align `MCPAuthService` to deterministic keys (remove stored `secret_key` column)
