# Dependency Injection Updates

This document describes the dependency injection changes made during the task service refactoring and provides guidance for developers working with the updated system.

## Overview

The task service refactoring consolidated the task management functionality and updated the dependency injection patterns to support the new architecture. The changes maintain backward compatibility while providing a cleaner, more maintainable structure.

## Key Changes

### 1. TaskService Consolidation

**Before (Application Layer)**:
```python
# Old structure - separate application and domain services
from agentarea_tasks.application.task_service import TaskService  # Removed
from agentarea_tasks.domain.task_service import DomainTaskService  # Removed
```

**After (Unified Domain Service)**:
```python
# New structure - single consolidated service
from agentarea_tasks.task_service import TaskService
```

### 2. Updated Dependency Injection

**New TaskService Factory**:
```python
async def get_task_service(
    db_session: DatabaseSessionDep,
    event_broker: EventBrokerDep,
) -> TaskService:
    """Get TaskService instance with injected TaskManager and AgentRepository."""
    from agentarea_tasks.task_service import TaskService
    from agentarea_tasks.temporal_task_manager import TemporalTaskManager
    
    # Get dependencies - these are now properly injected via FastAPI
    task_repository = await get_task_repository(db_session)
    agent_repository = await get_agent_repository(db_session)
    
    # Create task manager with repository
    task_manager = TemporalTaskManager(task_repository)
    
    # Create service with repository, event broker, task manager, and agent repository
    return TaskService(
        task_repository=task_repository,
        event_broker=event_broker,
        task_manager=task_manager,
        agent_repository=agent_repository,
    )
```

### 3. Service Dependencies

The TaskService now requires these dependencies:
- **TaskRepository**: For task persistence
- **EventBroker**: For domain event publishing
- **TaskManager**: For task execution (TemporalTaskManager)
- **AgentRepository**: For agent validation (optional)

## Service Interface

### Core Methods

The TaskService provides these primary methods:

```python
class TaskService(BaseTaskService):
    # Core CRUD operations
    async def create_task(self, task: SimpleTask) -> SimpleTask
    async def get_task(self, task_id: UUID) -> Optional[SimpleTask]
    async def update_task(self, task: SimpleTask) -> SimpleTask
    async def list_tasks(self, **filters) -> List[SimpleTask]
    async def delete_task(self, task_id: UUID) -> bool
    
    # Task execution
    async def submit_task(self, task: SimpleTask) -> SimpleTask
    async def cancel_task(self, task_id: UUID) -> bool
    
    # Convenience methods
    async def create_task_from_params(self, **params) -> SimpleTask
    async def get_user_tasks(self, user_id: str, **options) -> List[SimpleTask]
    async def get_agent_tasks(self, agent_id: UUID, **options) -> List[SimpleTask]
```

### Compatibility Methods

For backward compatibility, these methods are also available:

```python
# Status and result queries
async def get_task_status(self, task_id: UUID) -> Optional[str]
async def get_task_result(self, task_id: UUID) -> Optional[Any]
async def update_task_status(self, task_id: UUID, status: str, **options) -> SimpleTask

# Agent-specific operations
async def list_agent_tasks(self, agent_id: UUID, limit: int = 100) -> List[SimpleTask]

# Legacy execution methods (deprecated but functional)
async def execute_task(self, task_id: UUID, **options) -> AsyncGenerator
async def create_and_execute_task(self, **params) -> AsyncGenerator
```

## Usage Examples

### Basic Task Operations

```python
from agentarea_api.api.deps.services import get_task_service
from fastapi import Depends

async def create_task_endpoint(
    task_service: TaskService = Depends(get_task_service)
):
    # Create a new task
    task = SimpleTask(
        title="Example Task",
        description="Task description",
        query="Task query",
        user_id="user123",
        agent_id=agent_id,
        status="submitted"
    )
    
    # Submit for execution
    created_task = await task_service.submit_task(task)
    return created_task
```

### Task Status Updates

```python
async def update_task_endpoint(
    task_id: UUID,
    task_service: TaskService = Depends(get_task_service)
):
    # Update task status
    updated_task = await task_service.update_task_status(
        task_id=task_id,
        status="completed",
        result={"output": "Task completed successfully"}
    )
    return updated_task
```

### Agent Task Listing

```python
async def list_agent_tasks_endpoint(
    agent_id: UUID,
    task_service: TaskService = Depends(get_task_service)
):
    # Get tasks for specific agent
    tasks = await task_service.get_agent_tasks(
        agent_id=agent_id,
        limit=50
    )
    return tasks
```

## Migration Guide

### For API Endpoints

No changes required. All existing API endpoints continue to work with the updated dependency injection.

### For Internal Services

If you have services that directly import TaskService:

**Old Import**:
```python
from agentarea_tasks.application.task_service import TaskService
```

**New Import**:
```python
from agentarea_tasks.task_service import TaskService
```

### For Custom Task Managers

If you have custom task managers, ensure they implement the `BaseTaskManager` interface:

```python
from agentarea_tasks.domain.interfaces import BaseTaskManager

class CustomTaskManager(BaseTaskManager):
    async def submit_task(self, task: SimpleTask) -> SimpleTask:
        # Your implementation
        pass
    
    async def cancel_task(self, task_id: UUID) -> bool:
        # Your implementation
        pass
```

## Testing

### Unit Testing

Test your services with mocked dependencies:

```python
import pytest
from unittest.mock import AsyncMock
from agentarea_tasks.task_service import TaskService

@pytest.fixture
async def task_service():
    mock_repository = AsyncMock()
    mock_event_broker = AsyncMock()
    mock_task_manager = AsyncMock()
    mock_agent_repository = AsyncMock()
    
    return TaskService(
        task_repository=mock_repository,
        event_broker=mock_event_broker,
        task_manager=mock_task_manager,
        agent_repository=mock_agent_repository
    )

async def test_task_creation(task_service):
    # Test task creation
    task = SimpleTask(...)
    result = await task_service.create_task(task)
    assert result.id is not None
```

### Integration Testing

Use the provided test fixtures:

```python
from tests.conftest import db_session

async def test_task_service_integration(db_session):
    # Use real database session for integration tests
    from agentarea_api.api.deps.services import get_task_service
    
    # Create service with real dependencies
    task_service = await get_task_service(db_session, mock_event_broker)
    
    # Test real operations
    task = await task_service.create_task(...)
    assert task.id is not None
```

## Best Practices

### 1. Use Dependency Injection

Always use FastAPI's dependency injection rather than creating services manually:

```python
# Good
async def endpoint(task_service: TaskService = Depends(get_task_service)):
    return await task_service.get_task(task_id)

# Avoid
async def endpoint():
    task_service = TaskService(...)  # Manual creation
    return await task_service.get_task(task_id)
```

### 2. Handle Errors Gracefully

The TaskService raises specific exceptions:

```python
from agentarea_tasks.domain.base_service import TaskValidationError, TaskNotFoundError

try:
    task = await task_service.get_task(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Task not found")
except TaskValidationError as e:
    raise HTTPException(status_code=400, detail=str(e))
```

### 3. Use Type Hints

Leverage the provided type annotations:

```python
from agentarea_api.api.deps.services import TaskServiceDep

async def endpoint(task_service: TaskServiceDep):
    # Type hints provide better IDE support and error checking
    tasks: List[SimpleTask] = await task_service.list_tasks()
    return tasks
```

## Troubleshooting

### Common Issues

1. **Import Errors**: Update import paths to use the new consolidated service
2. **Missing Dependencies**: Ensure all required services are available in DI container
3. **Type Errors**: Use the provided type annotations and dependencies

### Debug Commands

```python
# Check service dependencies
from agentarea_api.api.deps.services import get_task_service
import inspect

sig = inspect.signature(get_task_service)
print("Dependencies:", list(sig.parameters.keys()))

# Verify service methods
from agentarea_tasks.task_service import TaskService
methods = [m for m in dir(TaskService) if not m.startswith('_')]
print("Available methods:", methods)
```

## Performance Considerations

### Connection Pooling

The dependency injection system reuses database connections efficiently:

```python
# Database sessions are properly managed
async def get_task_service(
    db_session: DatabaseSessionDep,  # Reused connection
    event_broker: EventBrokerDep,    # Singleton instance
) -> TaskService:
    # Service instances are created per request
    # but dependencies are efficiently managed
```

### Caching

Consider caching for frequently accessed data:

```python
from functools import lru_cache

@lru_cache(maxsize=100)
async def get_cached_task_status(task_id: UUID) -> str:
    # Cache task status for performance
    pass
```

## Future Considerations

### Planned Improvements

1. **Service Registry**: Centralized service discovery
2. **Health Checks**: Automatic dependency health monitoring
3. **Metrics**: Service performance tracking
4. **Configuration**: Dynamic service configuration

### Extensibility

The current architecture supports:
- Custom task managers
- Additional event handlers
- Extended validation rules
- Custom repository implementations

This provides a solid foundation for future enhancements while maintaining backward compatibility.