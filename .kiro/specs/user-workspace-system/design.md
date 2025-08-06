# Design Document

## Overview

This design implements a comprehensive workspace-scoped system for AgentArea that provides multi-tenant data isolation through JWT token-based context extraction and automatic repository-level filtering. The system ensures all database operations are scoped to the appropriate workspace with created_by audit trails, without requiring manual filtering in business logic. Resources are shared at the workspace level rather than being user-specific.

## Architecture

### High-Level Architecture

```mermaid
graph TB
    Client[Client Application] --> JWT[JWT Token]
    JWT --> Middleware[Auth Middleware]
    Middleware --> Context[Request Context]
    Context --> Services[Business Services]
    Services --> Repositories[Repository Layer]
    Repositories --> Database[(PostgreSQL)]
    
    subgraph "Context Flow"
        JWT --> |Extract Claims| UserID[user_id]
        JWT --> |Extract Claims| WorkspaceID[workspace_id]
        UserID --> Context
        WorkspaceID --> Context
    end
    
    subgraph "Data Isolation"
        Repositories --> |Auto-filter| WorkspaceFilter[WHERE workspace_id = ?]
        Repositories --> |Auto-populate| WorkspaceFields[workspace_id, created_by]
    end
```

### Component Architecture

The system consists of four main layers:

1. **Authentication Layer**: JWT token extraction and validation
2. **Context Layer**: User and workspace context management
3. **Repository Layer**: Automatic filtering and field population
4. **Database Layer**: Enhanced models with workspace_id and created_by

## Components and Interfaces

### 1. JWT Authentication Context

```python
from dataclasses import dataclass
from typing import Optional
from uuid import UUID

@dataclass
class UserContext:
    """User context extracted from JWT token."""
    user_id: str
    workspace_id: str
    email: Optional[str] = None
    roles: list[str] = None
    
    def __post_init__(self):
        if self.roles is None:
            self.roles = []
```

### 2. JWT Token Handler

```python
from fastapi import HTTPException, Request
from jose import JWTError, jwt
import logging

class JWTTokenHandler:
    """Handles JWT token extraction and validation."""
    
    def __init__(self, secret_key: str, algorithm: str = "HS256"):
        self.secret_key = secret_key
        self.algorithm = algorithm
        self.logger = logging.getLogger(__name__)
    
    async def extract_user_context(self, request: Request) -> UserContext:
        """Extract user context from JWT token in request."""
        token = self._extract_token_from_header(request)
        if not token:
            raise HTTPException(status_code=401, detail="Missing authorization token")
        
        try:
            payload = jwt.decode(token, self.secret_key, algorithms=[self.algorithm])
            return UserContext(
                user_id=payload.get("sub"),
                workspace_id=payload.get("workspace_id"),
                email=payload.get("email"),
                roles=payload.get("roles", [])
            )
        except JWTError as e:
            self.logger.error(f"JWT validation failed: {e}")
            raise HTTPException(status_code=401, detail="Invalid token")
    
    def _extract_token_from_header(self, request: Request) -> Optional[str]:
        """Extract Bearer token from Authorization header."""
        auth_header = request.headers.get("authorization")
        if auth_header and auth_header.startswith("Bearer "):
            return auth_header[7:]  # Remove "Bearer " prefix
        return None
```

### 3. Context Dependency

```python
from fastapi import Depends, Request
from typing import Annotated

async def get_user_context(request: Request) -> UserContext:
    """FastAPI dependency to extract user context from JWT."""
    token_handler = JWTTokenHandler(secret_key=get_settings().jwt_secret)
    return await token_handler.extract_user_context(request)

# Type alias for easier use
UserContextDep = Annotated[UserContext, Depends(get_user_context)]
```

### 4. Enhanced Base Repository

```python
from abc import ABC, abstractmethod
from typing import Generic, TypeVar, Optional, List
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, delete
from sqlalchemy.orm import DeclarativeBase

T = TypeVar('T', bound=DeclarativeBase)

class WorkspaceScopedRepository(Generic[T], ABC):
    """Base repository with automatic workspace filtering."""
    
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context
    
    @property
    @abstractmethod
    def model_class(self) -> type[T]:
        """Return the SQLAlchemy model class."""
        pass
    
    async def create(self, **kwargs) -> T:
        """Create a new record with automatic workspace/creator population."""
        # Automatically set created_by and workspace_id
        kwargs['created_by'] = self.user_context.user_id
        kwargs['workspace_id'] = self.user_context.workspace_id
        
        instance = self.model_class(**kwargs)
        self.session.add(instance)
        await self.session.flush()
        return instance
    
    async def get_by_id(self, id: UUID) -> Optional[T]:
        """Get record by ID with workspace filtering."""
        stmt = select(self.model_class).where(
            self.model_class.id == id,
            self.model_class.workspace_id == self.user_context.workspace_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()
    
    async def list_all(self, limit: int = 100, offset: int = 0, created_by: Optional[str] = None) -> List[T]:
        """List all workspace records with optional creator filtering."""
        stmt = select(self.model_class).where(
            self.model_class.workspace_id == self.user_context.workspace_id
        )
        
        # Optional filtering by creator
        if created_by == "me":
            stmt = stmt.where(self.model_class.created_by == self.user_context.user_id)
        elif created_by:
            stmt = stmt.where(self.model_class.created_by == created_by)
            
        stmt = stmt.limit(limit).offset(offset)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
    
    async def update(self, id: UUID, **kwargs) -> Optional[T]:
        """Update record with workspace verification."""
        # First verify the record exists in the current workspace
        existing = await self.get_by_id(id)
        if not existing:
            return None
        
        # Remove created_by and workspace_id from updates (they shouldn't change)
        kwargs.pop('created_by', None)
        kwargs.pop('workspace_id', None)
        
        stmt = update(self.model_class).where(
            self.model_class.id == id,
            self.model_class.workspace_id == self.user_context.workspace_id
        ).values(**kwargs)
        
        await self.session.execute(stmt)
        return await self.get_by_id(id)
    
    async def delete(self, id: UUID) -> bool:
        """Delete record with workspace verification."""
        stmt = delete(self.model_class).where(
            self.model_class.id == id,
            self.model_class.workspace_id == self.user_context.workspace_id
        )
        result = await self.session.execute(stmt)
        return result.rowcount > 0
```

### 5. WorkspaceScopedMixin

```python
from sqlalchemy import Column, String
from sqlalchemy.orm import Mapped, mapped_column
from agentarea_common.base.models import BaseModel

class WorkspaceScopedMixin:
    """Mixin for workspace-scoped models with audit trail."""
    
    workspace_id: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    created_by: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    
    def is_in_workspace(self, workspace_id: str) -> bool:
        """Check if this resource belongs to the specified workspace."""
        return self.workspace_id == workspace_id
    
    def is_created_by(self, user_id: str) -> bool:
        """Check if this resource was created by the specified user."""
        return self.created_by == user_id

# Enhanced base model combining BaseModel with WorkspaceScopedMixin
class WorkspaceScopedModel(BaseModel, WorkspaceScopedMixin):
    """Base model with workspace scoping and audit trail."""
    __abstract__ = True
```

### 6. Repository Factory

```python
from typing import Type, TypeVar
from sqlalchemy.ext.asyncio import AsyncSession

R = TypeVar('R', bound=WorkspaceScopedRepository)

class RepositoryFactory:
    """Factory for creating workspace-scoped repositories."""
    
    def __init__(self, session: AsyncSession, user_context: UserContext):
        self.session = session
        self.user_context = user_context
    
    def create_repository(self, repository_class: Type[R]) -> R:
        """Create a repository instance with user context."""
        return repository_class(self.session, self.user_context)

# FastAPI dependency
async def get_repository_factory(
    session: DatabaseSessionDep,
    user_context: UserContextDep
) -> RepositoryFactory:
    """Get repository factory with user context."""
    return RepositoryFactory(session, user_context)

RepositoryFactoryDep = Annotated[RepositoryFactory, Depends(get_repository_factory)]
```

## Data Models

### Enhanced Database Models

All existing models will be updated to inherit from the new WorkspaceScopedModel:

```python
# agents/domain/models.py
class Agent(WorkspaceScopedModel):
    __tablename__ = "agents"
    
    name: Mapped[str] = mapped_column(String, nullable=False)
    status: Mapped[str] = mapped_column(String, nullable=False, default="active")
    # ... other fields remain the same
    # workspace_id and created_by inherited from WorkspaceScopedModel

# tasks/infrastructure/orm.py  
class TaskORM(WorkspaceScopedModel):
    __tablename__ = "tasks"
    
    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    # ... other fields remain the same
    # workspace_id and created_by inherited from WorkspaceScopedModel

# triggers/infrastructure/orm.py
class TriggerORM(WorkspaceScopedModel):
    __tablename__ = "triggers"
    
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    agent_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), nullable=False)
    # ... other fields remain the same
    # workspace_id and created_by inherited from WorkspaceScopedModel
```

### Database Indexes

```sql
-- Add composite indexes for efficient workspace filtering
CREATE INDEX idx_agents_workspace_id ON agents(workspace_id);
CREATE INDEX idx_agents_workspace_user ON agents(workspace_id, created_by);

CREATE INDEX idx_tasks_workspace_id ON tasks(workspace_id);
CREATE INDEX idx_tasks_workspace_user ON tasks(workspace_id, created_by);
CREATE INDEX idx_tasks_workspace_agent ON tasks(workspace_id, agent_id);

CREATE INDEX idx_triggers_workspace_id ON triggers(workspace_id);
CREATE INDEX idx_triggers_workspace_user ON triggers(workspace_id, created_by);
CREATE INDEX idx_triggers_workspace_agent ON triggers(workspace_id, agent_id);

CREATE INDEX idx_trigger_executions_workspace_id ON trigger_executions(workspace_id);
```

## Error Handling

### Custom Exceptions

```python
class WorkspaceError(Exception):
    """Base exception for workspace-related errors."""
    pass

class WorkspaceAccessDenied(WorkspaceError):
    """Raised when user tries to access resource from different workspace."""
    pass

class MissingWorkspaceContext(WorkspaceError):
    """Raised when workspace context is missing from request."""
    pass

class InvalidJWTToken(WorkspaceError):
    """Raised when JWT token is invalid or missing required claims."""
    pass
```

### Error Handler

```python
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse

async def workspace_error_handler(request: Request, exc: WorkspaceError):
    """Handle workspace-related errors."""
    if isinstance(exc, WorkspaceAccessDenied):
        return JSONResponse(
            status_code=404,  # Return 404 instead of 403 to avoid info leakage
            content={
                "error": "Resource not found",
                "detail": "The requested resource does not exist or you don't have access to it"
            }
        )
    elif isinstance(exc, MissingWorkspaceContext):
        return JSONResponse(
            status_code=400,
            content={
                "error": "Missing workspace context",
                "detail": "Request must include valid user and workspace information"
            }
        )
    elif isinstance(exc, InvalidJWTToken):
        return JSONResponse(
            status_code=401,
            content={
                "error": "Authentication failed",
                "detail": "Invalid or missing authentication token"
            }
        )
    else:
        return JSONResponse(
            status_code=500,
            content={
                "error": "Internal server error",
                "detail": "An unexpected error occurred"
            }
        )
```

## Testing Strategy

### Unit Tests

```python
import pytest
from unittest.mock import Mock, AsyncMock
from agentarea_common.auth.context import UserContext
from agentarea_common.repositories.base import WorkspaceScopedRepository

class TestWorkspaceScopedRepository:
    @pytest.fixture
    def user_context(self):
        return UserContext(
            user_id="test-user",
            workspace_id="test-workspace"
        )
    
    @pytest.fixture
    def mock_session(self):
        return AsyncMock()
    
    async def test_create_auto_populates_context(self, mock_session, user_context):
        """Test that create() automatically populates created_by and workspace_id."""
        repo = TestRepository(mock_session, user_context)
        
        await repo.create(name="test")
        
        # Verify the model was created with context fields
        mock_session.add.assert_called_once()
        created_instance = mock_session.add.call_args[0][0]
        assert created_instance.created_by == "test-user"
        assert created_instance.workspace_id == "test-workspace"
    
    async def test_get_by_id_filters_by_workspace(self, mock_session, user_context):
        """Test that get_by_id() filters by workspace_id."""
        repo = TestRepository(mock_session, user_context)
        
        await repo.get_by_id("test-id")
        
        # Verify the query included workspace filter
        mock_session.execute.assert_called_once()
        # Additional assertions on the query structure
```

### Integration Tests

```python
import pytest
from fastapi.testclient import TestClient
from agentarea_api.main import app

class TestWorkspaceIsolation:
    @pytest.fixture
    def client(self):
        return TestClient(app)
    
    def test_workspace_isolation_agents(self, client):
        """Test that agents are isolated by workspace."""
        # Create agent in workspace A
        response_a = client.post(
            "/api/v1/agents",
            json={"name": "Agent A"},
            headers={"Authorization": "Bearer workspace_a_token"}
        )
        agent_a_id = response_a.json()["id"]
        
        # Try to access from workspace B
        response_b = client.get(
            f"/api/v1/agents/{agent_a_id}",
            headers={"Authorization": "Bearer workspace_b_token"}
        )
        
        assert response_b.status_code == 404
    
    def test_workspace_filtering_lists(self, client):
        """Test that list endpoints filter by workspace and return all workspace resources."""
        # Create agents in different workspaces by different users
        client.post(
            "/api/v1/agents",
            json={"name": "Agent A"},
            headers={"Authorization": "Bearer workspace_a_user1_token"}
        )
        client.post(
            "/api/v1/agents",
            json={"name": "Agent A2"},
            headers={"Authorization": "Bearer workspace_a_user2_token"}
        )
        client.post(
            "/api/v1/agents", 
            json={"name": "Agent B"},
            headers={"Authorization": "Bearer workspace_b_token"}
        )
        
        # List from workspace A should show both Agent A and Agent A2 (workspace-scoped)
        response_a = client.get(
            "/api/v1/agents",
            headers={"Authorization": "Bearer workspace_a_user1_token"}
        )
        
        agents_a = response_a.json()
        assert len(agents_a) == 2
        agent_names = [agent["name"] for agent in agents_a]
        assert "Agent A" in agent_names
        assert "Agent A2" in agent_names
        
        # Optional filtering by creator
        response_a_filtered = client.get(
            "/api/v1/agents?created_by=me",
            headers={"Authorization": "Bearer workspace_a_user1_token"}
        )
        
        agents_a_filtered = response_a_filtered.json()
        assert len(agents_a_filtered) == 1
        assert agents_a_filtered[0]["name"] == "Agent A"
```

## Migration Strategy

### Database Migration

```python
"""Add created_by and workspace_id to all tables

Revision ID: add_user_workspace_fields
Revises: previous_revision
Create Date: 2024-01-XX XX:XX:XX.XXXXXX
"""

from alembic import op
import sqlalchemy as sa

def upgrade():
    # Add created_by and workspace_id columns to all tables
    tables = ['agents', 'tasks', 'triggers', 'trigger_executions', 'mcp_server_instances']
    
    for table in tables:
        # Add columns as non-nullable with default values
        op.add_column(table, sa.Column('created_by', sa.String(255), nullable=False, server_default='system'))
        op.add_column(table, sa.Column('workspace_id', sa.String(255), nullable=False, server_default='default'))
    
    # Remove server defaults after adding columns
    for table in tables:
        op.alter_column(table, 'created_by', server_default=None)
        op.alter_column(table, 'workspace_id', server_default=None)
    
    # Add indexes for efficient workspace filtering
    for table in tables:
        op.create_index(f'idx_{table}_workspace_id', table, ['workspace_id'])
        op.create_index(f'idx_{table}_workspace_user', table, ['workspace_id', 'created_by'])

def downgrade():
    tables = ['agents', 'tasks', 'triggers', 'trigger_executions', 'mcp_server_instances']
    
    for table in tables:
        op.drop_index(f'idx_{table}_workspace_user', table)
        op.drop_index(f'idx_{table}_workspace_id', table)
        op.drop_column(table, 'workspace_id')
        op.drop_column(table, 'created_by')
```

### Service Updates

All existing services will be updated to use the new repository pattern:

```python
# Before
class AgentService:
    def __init__(self, repository: AgentRepository, event_broker: EventBroker):
        self.repository = repository
        self.event_broker = event_broker

# After  
class AgentService:
    def __init__(self, repository_factory: RepositoryFactory, event_broker: EventBroker):
        self.repository_factory = repository_factory
        self.event_broker = event_broker
        
    async def create_agent(self, **kwargs) -> Agent:
        repository = self.repository_factory.create_repository(AgentRepository)
        return await repository.create(**kwargs)
```

This design ensures complete workspace isolation while maintaining clean separation of concerns and providing a smooth migration path for existing code.