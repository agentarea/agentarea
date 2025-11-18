# MCP Infrastructure Architecture

## Overview

The MCP (Model Context Protocol) infrastructure implements a distributed, event-driven architecture for managing MCP server instances. The system supports both containerized and URL-based MCP servers with dynamic configuration and secret management.

## Architecture Patterns

### 1. Event-Driven Architecture

**Pattern**: Domain Events + Redis Pub/Sub
**Implementation**: 
- Python FastAPI publishes domain events to Redis
- Go MCP Manager subscribes to events and handles container lifecycle
- Async communication ensures loose coupling

```
Python API ──(Domain Events)──> Redis ──(Pub/Sub)──> Go MCP Manager
     │                                                      │
     └── PostgreSQL Database                                └── Podman Containers
```

**Key Components**:
- `MCPServerInstanceCreated` events trigger container creation
- `MCPServerInstanceDeleted` events trigger container cleanup
- Event payload includes complete configuration (`json_spec`)

### 2. Unified Configuration Pattern

**Pattern**: JSON Specification with Schema Validation
**Implementation**: Industry-standard connector design

```python
# MCPServer defines the schema
env_schema = [
    {
        "name": "API_KEY",
        "type": "string", 
        "description": "API key for service",
        "required": True,
        "secret": True
    }
]

# MCPServerInstance contains the actual configuration
json_spec = {
    "type": "docker",  # or "url"
    "image": "mcp/filesystem:latest",
    "port": 8001,
    "environment": {
        "API_KEY": "secret_ref:instance_123:API_KEY"
    },
    "command": ["python", "-m", "mcp_filesystem"],
    "resources": {
        "memory_limit": "256m",
        "cpu_limit": "0.5"
    }
}
```

### 3. Secret Management Pattern

**Pattern**: Reference-based Secret Storage
**Implementation**: 
- Environment variables stored as references in `json_spec`
- Actual values stored in secret manager (Infisical/DB)
- Go service resolves secrets at container runtime

```
json_spec.environment.API_KEY = "secret_ref:instance_123:API_KEY"
                                      ↓
Secret Manager: "instance_123:API_KEY" → "actual_secret_value"
                                      ↓
Container Environment: API_KEY=actual_secret_value
```

### 4. Multi-Provider Pattern

**Pattern**: Type-based Provider Selection
**Implementation**: Support for different MCP deployment types

#### Docker Provider
```json
{
    "type": "docker",
    "image": "agentarea/echo:latest",
    "port": 8080,
    "environment": {...},
    "command": [...],
    "resources": {...}
}
```

#### URL Provider  
```json
{
    "type": "url",
    "endpoint": "http://localhost:3333/mcp",
    "health_check": "/health",
    "timeout": 30
}
```

### 5. Repository Pattern

**Pattern**: Domain-Driven Repository with Event Publishing
**Implementation**:
- Separate repositories for `MCPServer` and `MCPServerInstance`
- Event publishing integrated into service layer
- Clean separation of persistence and business logic

### 6. Dependency Injection Pattern

**Pattern**: FastAPI Dependency Injection
**Implementation**:
- Services injected via `Depends()`
- Secret manager, event broker, repositories all injectable
- Enables testing with mock implementations

## Data Models

### MCPServer (Schema Definition)
```python
class MCPServer:
    id: UUID
    name: str
    description: str
    docker_image_url: str  # Default image for docker type
    version: str
    tags: List[str]
    status: str
    is_public: bool
    env_schema: List[Dict[str, Any]]  # Defines required environment variables
```

### MCPServerInstance (Runtime Configuration)
```python
class MCPServerInstance:
    id: UUID
    name: str
    description: Optional[str]
    server_spec_id: Optional[str]  # Reference to MCPServer
    json_spec: Dict[str, Any]      # Complete runtime configuration
    status: str
```

## Environment Schema Structure

The `env_schema` in `MCPServer` defines the contract for environment variables:

```python
env_schema = [
    {
        "name": "API_KEY",
        "type": "string",
        "description": "API key for external service",
        "required": True,
        "secret": True,
        "default": None
    },
    {
        "name": "MAX_CONNECTIONS", 
        "type": "integer",
        "description": "Maximum number of connections",
        "required": False,
        "secret": False,
        "default": "10"
    }
]
```

## JSON Spec Structure

The `json_spec` in `MCPServerInstance` contains the complete runtime configuration:

### Docker Type
```json
{
    "type": "docker",
    "image": "mcp/filesystem:latest",
    "port": 8001,
    "environment": {
        "ALLOWED_DIRECTORIES": "/tmp,/var/tmp",
        "MAX_FILE_SIZE": "5MB",
        "API_KEY": "secret_ref:instance_123:API_KEY"
    },
    "command": ["python", "-m", "mcp_filesystem"],
    "resources": {
        "memory_limit": "256m", 
        "cpu_limit": "0.5"
    },
    "health_check": {
        "path": "/health",
        "interval": 30,
        "timeout": 10
    }
}
```

### URL Type
```json
{
    "type": "url",
    "endpoint": "http://localhost:3333/mcp",
    "health_check": {
        "path": "/health",
        "interval": 30,
        "timeout": 10
    },
    "authentication": {
        "type": "bearer",
        "token": "secret_ref:instance_123:AUTH_TOKEN"
    }
}
```

## Service Architecture

### Python FastAPI Services
- **MCPServerService**: Manages server definitions and schemas
- **MCPServerInstanceService**: Manages instance lifecycle and configuration
- **MCPEnvironmentService**: Handles secret storage and retrieval
- **EventBroker**: Publishes domain events to Redis

### Go MCP Manager Services
- **EventSubscriber**: Listens for Redis events
- **ContainerManager**: Manages Podman containers
- **SecretResolver**: Resolves secret references (to be implemented)
- **HealthChecker**: Monitors container/URL health

## Event Flow

1. **Instance Creation**:
   ```
   API Request → MCPServerInstanceService → Database → Event Published → 
   Redis → Go EventSubscriber → ContainerManager → Podman Container
   ```

2. **Secret Resolution**:
   ```
   json_spec.environment → SecretResolver → Secret Manager → 
   Actual Values → Container Environment
   ```

3. **Health Monitoring**:
   ```
   HealthChecker → Container/URL Status → Database Update → 
   Status Events → API Response
   ```

## Network Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Python API    │    │   Go Manager    │    │   MCP Containers│
│   (Port 8000)   │    │   (Port 7999)   │    │   (Dynamic)     │
└─────────────────┘    └─────────────────┘    └─────────────────┘
         │                       │                       │
         └───────────────────────┼───────────────────────┘
                                 │
         ┌─────────────────┐    ┌─────────────────┐
         │     Redis       │    │   PostgreSQL    │
         │   (Port 6379)   │    │   (Port 5432)   │
         └─────────────────┘    └─────────────────┘
                                 │
         ┌─────────────────┐    ┌─────────────────┐
         │     Traefik     │    │   Secret Store  │
         │   (Port 81)     │    │   (Infisical)   │
         └─────────────────┘    └─────────────────┘
```

## Security Patterns

### 1. Secret Isolation
- Secrets never stored in `json_spec` directly
- Reference-based storage with resolution at runtime
- Separate secret manager with encrypted storage

### 2. Network Isolation
- MCP containers on isolated network
- Reverse proxy (Traefik) for external access
- Internal service communication only

### 3. Resource Limits
- Container resource constraints (CPU, memory)
- Maximum container limits per instance
- Health check timeouts and retries

## Implementation Status

### ✅ Completed
- Event-driven architecture with Redis
- Basic container management with Podman
- Database models and repositories
- API endpoints for CRUD operations
- Network configuration and service discovery

### 🚧 In Progress
- Event parsing and data extraction (minor bug fix needed)
- Container creation from `json_spec`

### 📋 Future Enhancements
- Secret resolution in Go service
- URL-based MCP provider support
- Health monitoring and status updates
- Resource management and cleanup
- Production deployment configuration

## Testing Strategy

### Integration Tests
- End-to-end flow from API to container creation
- Event publishing and consumption
- Secret management integration
- Health check validation

### Test Containers
- `agentarea/echo`: Simple HTTP echo server for testing
- `mcp/filesystem`: Filesystem MCP server
- URL endpoint: `localhost:3333/mcp` for URL-based testing

## Configuration Examples

### Example 1: Docker-based MCP Server
```python
# Server definition
server = {
    "name": "filesystem-mcp",
    "description": "Filesystem access MCP server",
    "docker_image_url": "mcp/filesystem:latest",
    "env_schema": [
        {"name": "ALLOWED_DIRECTORIES", "type": "string", "required": True},
        {"name": "MAX_FILE_SIZE", "type": "string", "required": False, "default": "10MB"}
    ]
}

# Instance configuration
instance = {
    "name": "fs-instance-1",
    "server_spec_id": server_id,
    "json_spec": {
        "type": "docker",
        "image": "mcp/filesystem:latest",
        "port": 8001,
        "environment": {
            "ALLOWED_DIRECTORIES": "/tmp,/var/tmp",
            "MAX_FILE_SIZE": "5MB"
        }
    }
}
```

### Example 2: URL-based MCP Server
```python
# Server definition (minimal for URL type)
server = {
    "name": "external-mcp",
    "description": "External MCP service",
    "docker_image_url": "",  # Not used for URL type
    "env_schema": []
}

# Instance configuration
instance = {
    "name": "external-instance-1", 
    "server_spec_id": server_id,
    "json_spec": {
        "type": "url",
        "endpoint": "http://localhost:3333/mcp",
        "health_check": {
            "path": "/health",
            "interval": 30
        }
    }
}
```

This architecture provides a flexible, scalable foundation for managing MCP servers with strong separation of concerns, event-driven communication, and secure secret management.