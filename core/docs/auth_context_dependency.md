# User Context Dependency

This document explains how to use the new JWT-based user context dependency system in AgentArea.

## Overview

The user context dependency system provides automatic extraction of user and workspace information from JWT tokens in FastAPI endpoints. This enables proper multi-tenant data isolation and user authentication throughout the application.

## Key Components

### UserContext

A dataclass that holds user and workspace information:

```python
@dataclass
class UserContext:
    user_id: str
    workspace_id: str
    email: Optional[str] = None
    roles: Optional[list[str]] = None
```

### UserContextDep

A FastAPI dependency type alias that automatically extracts user context from JWT tokens:

```python
UserContextDep = Annotated[UserContext, Depends(get_user_context)]
```

## Usage in Endpoints

### Basic Usage

```python
from fastapi import FastAPI
from agentarea_common.auth import UserContextDep

app = FastAPI()

@app.get("/user/profile")
async def get_user_profile(user_context: UserContextDep) -> dict:
    return {
        "user_id": user_context.user_id,
        "workspace_id": user_context.workspace_id,
        "email": user_context.email,
        "roles": user_context.roles
    }
```

### Role-Based Access Control

```python
@app.get("/admin/users")
async def list_users(user_context: UserContextDep) -> dict:
    if "admin" not in user_context.roles:
        raise HTTPException(status_code=403, detail="Admin role required")
    
    # Admin-only logic here
    return {"users": [...]}
```

### Workspace-Scoped Operations

```python
@app.post("/workspace/resources")
async def create_resource(
    resource_data: dict,
    user_context: UserContextDep
) -> dict:
    # The user_context.workspace_id and user_context.user_id
    # should be used to ensure proper data isolation
    return {
        "resource": resource_data,
        "created_by": user_context.user_id,
        "workspace_id": user_context.workspace_id
    }
```

## JWT Token Format

The JWT token must include the following claims:

- `sub`: User ID (required)
- `workspace_id`: Workspace ID (required)
- `email`: User email (optional)
- `roles`: List of user roles (optional, defaults to empty list)

Example JWT payload:
```json
{
  "sub": "user-123",
  "workspace_id": "workspace-456",
  "email": "user@example.com",
  "roles": ["user", "admin"],
  "iat": 1640995200,
  "exp": 1641081600
}
```

## Configuration

JWT settings are configured in the application settings:

```python
class AppSettings(BaseAppSettings):
    JWT_SECRET_KEY: str = "your-secret-key-change-in-production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
```

## Error Handling

The dependency automatically handles various error scenarios:

- **401 Unauthorized**: Missing or invalid JWT token
- **400 Bad Request**: JWT token missing required claims (`sub` or `workspace_id`)

## Testing

### Test Utilities

Use the provided test utilities to generate JWT tokens for testing:

```python
from agentarea_common.auth.test_utils import (
    generate_test_jwt_token,
    create_admin_test_token,
    create_basic_test_token
)

# Generate a custom test token
token = generate_test_jwt_token(
    user_id="test-user",
    workspace_id="test-workspace",
    email="test@example.com",
    roles=["user", "admin"]
)

# Generate an admin token
admin_token = create_admin_test_token()

# Generate a basic user token
user_token = create_basic_test_token()
```

### Testing Endpoints

```python
import pytest
from fastapi.testclient import TestClient
from agentarea_common.auth.test_utils import generate_test_jwt_token

def test_endpoint_with_auth():
    client = TestClient(app)
    
    token = generate_test_jwt_token(
        user_id="test-user",
        workspace_id="test-workspace"
    )
    
    response = client.get(
        "/user/profile",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200
    data = response.json()
    assert data["user_id"] == "test-user"
    assert data["workspace_id"] == "test-workspace"
```

## Best Practices

All endpoints should use `UserContextDep` for proper functionality and workspace isolation:

```python
@app.get("/agents")
async def list_agents(user_context: UserContextDep):
    # Automatic workspace isolation
    # user_context.user_id and user_context.workspace_id available
    pass
```

## Context Manager

The system also provides a context manager for accessing user context throughout the request lifecycle:

```python
from agentarea_common.auth import ContextManager

# Get current context (set automatically by the dependency)
context = ContextManager.get_context()
if context:
    print(f"Current user: {context.user_id}")
    print(f"Current workspace: {context.workspace_id}")
```

This is useful in service layers or other components that don't have direct access to the FastAPI dependency system.