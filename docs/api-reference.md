# API Reference

<Info>
AgentArea exposes a REST API built with FastAPI. All endpoints are documented with OpenAPI and available via interactive Swagger UI when running locally.
</Info>

## Interactive Documentation

When running AgentArea locally, access the full interactive API docs at:

- **Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **OpenAPI JSON**: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

## Authentication

All API requests require authentication via JWT bearer tokens or session cookies managed by Ory Kratos.

```bash
# Example: Authenticated request
curl -X GET http://localhost:8000/v1/agents \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

## API Endpoint Groups

<CardGroup cols={2}>
  <Card title="Agents" icon="robot">
    **`/v1/agents`**

    Create, read, update, and delete AI agents. Configure agent personalities, system prompts, and capabilities.
  </Card>

  <Card title="Skills" icon="wand-magic-sparkles">
    **`/v1/skills`**

    Manage reusable skill definitions that can be attached to agents. Skills define tools, prompts, and behaviors.
  </Card>

  <Card title="Tasks" icon="list-check">
    **`/v1/tasks`**

    Create and manage agent tasks. Stream task execution via SSE. Track task status and results.
  </Card>

  <Card title="MCP Servers" icon="plug">
    **`/v1/mcp-server-instances`**

    Provision and manage MCP server instances. Configure managed, remote, and compound MCP servers.
  </Card>

  <Card title="Triggers" icon="bolt">
    **`/v1/triggers`**

    Set up event-driven automation. Configure schedule, webhook, and event-based triggers for agents.
  </Card>

  <Card title="Events" icon="tower-broadcast">
    **`/v1/events`**

    Stream real-time events via SSE. Subscribe to task updates, agent status changes, and system events.
  </Card>
</CardGroup>

---

## Key Endpoints

### Agents

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/agents` | List all agents in workspace |
| `POST` | `/v1/agents` | Create a new agent |
| `GET` | `/v1/agents/{id}` | Get agent details |
| `PATCH` | `/v1/agents/{id}` | Update agent configuration |
| `DELETE` | `/v1/agents/{id}` | Delete an agent |

### Tasks

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/v1/tasks` | Create and execute a task |
| `GET` | `/v1/tasks/{id}` | Get task status and result |
| `GET` | `/v1/tasks/{id}/events` | Stream task events (SSE) |

### MCP Server Instances

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/mcp-server-instances` | List MCP server instances |
| `POST` | `/v1/mcp-server-instances` | Create a new MCP instance |
| `GET` | `/v1/mcp-server-instances/{id}` | Get instance details |
| `DELETE` | `/v1/mcp-server-instances/{id}` | Remove an instance |

### Skills

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/v1/skills` | List all skills |
| `POST` | `/v1/skills` | Create a new skill |
| `GET` | `/v1/skills/{id}` | Get skill details |
| `PATCH` | `/v1/skills/{id}` | Update a skill |

---

## Common Patterns

### Workspace Scoping

All API resources are scoped to the authenticated user's workspace. You do not need to pass a workspace ID explicitly -- it is derived from the authentication context.

### Pagination

List endpoints support cursor-based pagination:

```bash
GET /v1/agents?limit=20&offset=0
```

### Error Responses

All errors follow a consistent format:

```json
{
  "detail": "Agent not found",
  "status_code": 404
}
```

### SSE Streaming

Task execution events are streamed via Server-Sent Events:

```bash
curl -N http://localhost:8000/v1/tasks/{task_id}/events \
  -H "Authorization: Bearer YOUR_JWT_TOKEN"
```

Events are delivered as JSON payloads with `event` and `data` fields.

---

<Note>
For the complete, interactive API documentation with request/response schemas, run AgentArea locally and visit [http://localhost:8000/docs](http://localhost:8000/docs).
</Note>
