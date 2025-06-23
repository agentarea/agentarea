# MCP (Model Context Protocol) Integration

This module provides event-driven integration between the AgentArea core application and the MCP infrastructure.

## Architecture

The integration follows a **hybrid approach**:

1. **HTTP API**: Immediate operations (create, delete, status check)
2. **Event Bus**: Asynchronous state management and notifications
3. **Database**: Persistent storage of configurations and deployments

## Components

### Events (`events.py`)
- Event schemas for MCP server lifecycle
- Event types for auditing and monitoring
- Pydantic models for type safety

### Schemas (`schemas.py`)
- MCP server configuration models
- API request/response schemas
- Database models (TODO: implement with SQLAlchemy)

### Client (`client.py`)
- Hybrid HTTP + Event client for MCP Manager
- Connection management and error handling
- Singleton pattern for application-wide usage

### Handlers (`handlers.py`)
- FastStream event handlers for MCP events
- Database synchronization logic
- Audit trail management

## Usage

### Creating an MCP Server

```python
from agentarea.modules.mcp.schemas import MCPServerCreateRequest, MCPServerTemplate
from agentarea.modules.mcp.client import get_mcp_client

# Create request
request = MCPServerCreateRequest(
    agent_id=agent_id,
    service_name="my-fastapi-server",
    template=MCPServerTemplate.FASTAPI,
    environment={"DATABASE_URL": "sqlite:///app.db"},
    replicas=1
)

# Submit to MCP Manager
client = get_mcp_client()
response = await client.create_server(request, user_id=user_id)

if response.success:
    print(f"Server creation accepted: {response.config_id}")
else:
    print(f"Failed: {response.message}")
```

### Event Flow

1. **Request** → Core App receives MCP server creation request
2. **Validation** → HTTP call to MCP Manager for immediate validation
3. **Event** → Publish `mcp.server.create.requested` event
4. **Async Processing** → MCP Manager processes container creation
5. **Status Events** → MCP Manager publishes status updates
6. **Database Sync** → Event handlers update database with runtime info

## Configuration

Set these environment variables:

```bash
# MCP Manager connection
MCP_MANAGER_URL=http://mcp-manager:8000
MCP_CLIENT_TIMEOUT=30

# Event bus (Redis)
REDIS_URL=redis://redis:6379
```

## Security

- **Infrastructure permissions** handled by MCP Manager
- **Business permissions** handled by Core App
- **Audit trail** via event logging
- **Network isolation** via Docker networks

## Future Enhancements

- [ ] Database models with SQLAlchemy
- [ ] User authentication integration
- [ ] Resource quota management
- [ ] A2A communication protocols
- [ ] K8s operator migration path 