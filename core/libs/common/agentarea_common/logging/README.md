# AgentArea Audit Logging with Workspace Context

This module provides comprehensive audit logging with workspace context for the AgentArea platform. It ensures all resource operations are logged with proper user and workspace information for compliance, debugging, and analytics.

## Features

- **Structured JSON Logging**: All logs are formatted as JSON for easy parsing and analysis
- **Workspace Context**: Automatic inclusion of `user_id` and `workspace_id` in all log entries
- **Audit Events**: Structured logging for CRUD operations (Create, Read, Update, Delete, List)
- **Error Logging**: Comprehensive error logging with context
- **Query Support**: Built-in utilities for filtering and querying audit logs
- **Repository Integration**: Automatic audit logging in workspace-scoped repositories
- **FastAPI Middleware**: Request-level logging context management

## Quick Start

### 1. Setup Logging

```python
from agentarea_common.logging import setup_logging

# Setup structured logging with audit support
setup_logging(
    level="INFO",
    enable_structured_logging=True,
    enable_audit_logging=True
)
```

### 2. Use Audit Logger

```python
from agentarea_common.logging import get_audit_logger
from agentarea_common.auth.context import UserContext

# Get audit logger
audit_logger = get_audit_logger()
user_context = UserContext(user_id="alice", workspace_id="workspace-123")

# Log resource creation
audit_logger.log_create(
    resource_type="agent",
    user_context=user_context,
    resource_id="agent-001",
    resource_data={"name": "My Agent", "model": "gpt-4"}
)

# Log resource update
audit_logger.log_update(
    resource_type="agent",
    user_context=user_context,
    resource_id="agent-001",
    resource_data={"name": "Updated Agent"}
)

# Log resource deletion
audit_logger.log_delete(
    resource_type="agent",
    user_context=user_context,
    resource_id="agent-001"
)

# Log errors
audit_logger.log_error(
    resource_type="agent",
    user_context=user_context,
    error="Database connection failed",
    resource_id="agent-001"
)
```

### 3. Use Context Logger

```python
from agentarea_common.logging import get_context_logger

# Get context-aware logger
logger = get_context_logger("agentarea.agents", user_context)

# All log messages will include workspace context
logger.info("Processing agent request")
logger.error("Failed to process request", extra={"error_code": "PROC_001"})
```

### 4. Repository Integration

The `WorkspaceScopedRepository` automatically includes audit logging:

```python
from agentarea_common.base import WorkspaceScopedRepository

class AgentRepository(WorkspaceScopedRepository[Agent]):
    async def create_agent(self, name: str) -> Agent:
        # This will automatically log the creation
        return await self.create(name=name)
    
    async def update_agent(self, agent_id: str, name: str) -> Agent:
        # This will automatically log the update
        return await self.update(agent_id, name=name)
```

### 5. FastAPI Integration

```python
from fastapi import FastAPI
from agentarea_common.logging import LoggingContextMiddleware, setup_logging

app = FastAPI()

# Setup logging
setup_logging(enable_audit_logging=True)

# Add logging middleware
app.add_middleware(LoggingContextMiddleware)
```

## Log Format

All audit logs follow this structured JSON format:

```json
{
  "timestamp": "2024-01-01T12:00:00.000Z",
  "level": "INFO",
  "logger": "agentarea.audit",
  "message": "AUDIT: CREATE agent",
  "user_id": "alice",
  "workspace_id": "workspace-123",
  "audit_event": {
    "timestamp": "2024-01-01T12:00:00.000Z",
    "action": "create",
    "resource_type": "agent",
    "user_id": "alice",
    "workspace_id": "workspace-123",
    "resource_id": "agent-001",
    "resource_data": {
      "name": "My Agent",
      "model": "gpt-4"
    },
    "error": null,
    "additional_context": {
      "endpoint": "/api/v1/agents",
      "method": "POST"
    }
  },
  "resource_type": "agent",
  "action": "create"
}
```

## Querying Audit Logs

Use the `AuditLogQuery` utility to filter and search audit logs:

```python
from agentarea_common.logging import AuditLogQuery
from datetime import datetime, timedelta

query = AuditLogQuery("audit.log")

# Get user activity
user_activity = query.get_user_activity(
    user_context=user_context,
    start_time=datetime.now() - timedelta(days=1)
)

# Get workspace activity
workspace_activity = query.get_workspace_activity(
    workspace_id="workspace-123",
    limit=100
)

# Get resource history
agent_history = query.get_resource_history(
    resource_type="agent",
    resource_id="agent-001"
)

# Get error logs
error_logs = query.get_error_logs(
    workspace_id="workspace-123",
    start_time=datetime.now() - timedelta(hours=1)
)

# Custom filtering
custom_results = query.query_logs(
    workspace_id="workspace-123",
    action="create",
    resource_type="agent",
    limit=50
)
```

## Configuration

### Environment Variables

- `LOG_LEVEL`: Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
- `ENABLE_STRUCTURED_LOGGING`: Enable JSON structured logging (default: true)
- `ENABLE_AUDIT_LOGGING`: Enable audit logging (default: true)
- `AUDIT_LOG_FILE`: Path to audit log file (default: audit.log)

### Programmatic Configuration

```python
from agentarea_common.logging import setup_logging

setup_logging(
    level="INFO",
    enable_structured_logging=True,
    enable_audit_logging=True,
    user_context=user_context  # Optional: set default context
)
```

## Audit Actions

The system logs the following audit actions:

- **CREATE**: Resource creation
- **READ**: Resource access/retrieval
- **UPDATE**: Resource modification
- **DELETE**: Resource deletion
- **LIST**: Resource listing/querying
- **ERROR**: Error events with context

## Security and Compliance

### Data Privacy

- Sensitive data is not logged in resource_data by default
- PII should be excluded from audit logs
- Use additional_context for metadata only

### Retention

- Audit logs are rotated automatically (10MB files, 5 backups)
- Configure retention policies based on compliance requirements
- Consider archiving old audit logs to long-term storage

### Access Control

- Audit logs should be accessible only to authorized personnel
- Implement proper file permissions on audit log files
- Consider centralized log management for production

## Best Practices

### 1. Use Appropriate Log Levels

```python
# Use INFO for normal audit events
audit_logger.log_create(...)

# Use ERROR for actual errors
audit_logger.log_error(...)

# Use context logger for application logs
logger.info("Processing request")  # INFO
logger.warning("Deprecated API used")  # WARNING
logger.error("Request failed")  # ERROR
```

### 2. Include Relevant Context

```python
audit_logger.log_create(
    resource_type="agent",
    user_context=user_context,
    resource_id=agent.id,
    resource_data={"name": agent.name},  # Include relevant data
    endpoint=request.url.path,  # Include request context
    method=request.method,
    client_ip=request.client.host
)
```

### 3. Handle Errors Gracefully

```python
try:
    agent = await agent_service.create_agent(data)
    audit_logger.log_create("agent", user_context, agent.id, data)
except Exception as e:
    audit_logger.log_error("agent", user_context, str(e), request_data=data)
    raise
```

### 4. Filter Sensitive Data

```python
# Don't log sensitive information
safe_data = {k: v for k, v in agent_data.items() if k not in ['password', 'api_key']}
audit_logger.log_create("agent", user_context, agent.id, safe_data)
```

## Troubleshooting

### Common Issues

1. **Logs not appearing**: Check log level configuration
2. **Missing workspace context**: Ensure middleware is properly configured
3. **Performance issues**: Consider async logging for high-volume applications
4. **Disk space**: Monitor audit log file sizes and rotation

### Debug Mode

Enable debug logging to troubleshoot issues:

```python
setup_logging(level="DEBUG")
```

## Integration Examples

See `integration_example.py` for complete FastAPI integration examples and `demo.py` for a working demonstration of all features.

## Requirements

This module satisfies the following requirements from the user-workspace-system spec:

- **6.1**: Logs resource creation with created_by and workspace_id
- **6.2**: Logs resource updates with created_by and workspace_id  
- **6.3**: Logs resource deletions with created_by and workspace_id
- **6.4**: Logs errors with created_by and workspace_id context
- **6.5**: Supports filtering audit logs by created_by and workspace_id