# Dependency Injection Patterns in AgentArea

This document explains the improved patterns for managing dependencies like `EventBroker` instead of using global variables.

## Problems with Global Variables

The original pattern in `core/agentarea/api/deps/events.py` used a global variable:

```python
_event_broker = None

async def get_event_broker() -> EventBroker:
    global _event_broker
    if _event_broker is None:
        _event_broker = EventBroker()
    return _event_broker
```

### Issues with this approach:

1. **Thread Safety**: Global variables can cause race conditions
2. **Testing Difficulties**: Hard to mock or replace for testing
3. **Hidden Dependencies**: Makes dependencies unclear
4. **Lifecycle Management**: No clear control over object creation/destruction
5. **Singleton Anti-pattern**: Creates implicit singleton without proper controls

## Better Pythonic Solutions

### 1. Application Lifespan Management with Router Integration (Recommended)

**File: `core/agentarea/common/events/router.py`**
```python
from faststream.redis.fastapi import RedisRouter
from agentarea.config import RedisSettings
from .redis_event_broker import RedisEventBroker

def get_event_router(settings: RedisSettings) -> RedisRouter:
    """Factory function to create and configure a Redis event router."""
    router = RedisRouter(settings.REDIS_URL)
    return router

def create_event_broker_from_router(router: RedisRouter) -> RedisEventBroker:
    """Create an EventBroker instance from a router's underlying broker.
    
    This ensures the EventBroker uses the same broker instance as the router.
    """
    redis_broker = router.broker
    return RedisEventBroker(redis_broker)
```

**File: `core/agentarea/main.py`**
```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from agentarea.api.events.events_router import router as events_router
from agentarea.common.events.broker import EventBroker
from agentarea.common.events.router import create_event_broker_from_router

class AppState:
    event_broker: EventBroker | None = None

app_state = AppState()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup - Create EventBroker from router's broker
    try:
        event_broker = create_event_broker_from_router(events_router)
        app_state.event_broker = event_broker
    except ValueError:
        # Fallback to basic EventBroker if router doesn't support it
        event_broker = EventBroker()
        app_state.event_broker = event_broker
    
    yield
    
    # Shutdown
    app_state.event_broker = None

def create_app() -> FastAPI:
    return FastAPI(lifespan=lifespan)
```

**File: `core/agentarea/api/deps/events.py`**
```python
from typing import Annotated
from fastapi import Depends, HTTPException
from ...common.events.broker import EventBroker

async def get_event_broker() -> EventBroker:
    from ...main import app_state
    
    if app_state.event_broker is None:
        raise HTTPException(status_code=500, detail="EventBroker not initialized")
    
    return app_state.event_broker

EventBrokerDep = Annotated[EventBroker, Depends(get_event_broker)]
```

### 2. Dependency Injection Container (Advanced)

**File: `core/agentarea/common/di/container.py`**
```python
from typing import Any, Callable, Dict, TypeVar, Type

T = TypeVar('T')

class DIContainer:
    def __init__(self):
        self._singletons: Dict[Type[Any], Any] = {}
        self._factories: Dict[Type[Any], Callable[[], Any]] = {}
    
    def register_singleton(self, interface: Type[T], instance: T) -> None:
        self._singletons[interface] = instance
    
    def get(self, interface: Type[T]) -> T:
        if interface in self._singletons:
            return self._singletons[interface]
        # ... factory logic
        
_container = DIContainer()

def resolve(interface: Type[T]) -> T:
    return _container.get(interface)
```

### 3. Using Type Aliases for Clean Dependencies

**File: `core/agentarea/api/deps/services.py`**
```python
from .events import EventBrokerDep

async def get_agent_service(
    session: Annotated[AsyncSession, Depends(get_db_session)],
    event_broker: EventBrokerDep,  # Clean and reusable
) -> AgentService:
    repository = AgentRepository(session)
    return AgentService(repository, event_broker)
```

## Key Benefits of the Final Solution

### 1. **Shared Broker Instance**
The EventBroker now uses the exact same Redis broker instance as the FastStream router, ensuring:
- No connection duplication
- Consistent configuration
- Shared connection pool
- Unified event handling

### 2. **Testability**
```python
# Easy to mock in tests
app.dependency_overrides[get_event_broker] = lambda: mock_broker

# Or with DI container
container.register_singleton(EventBroker, mock_broker)
```

### 3. **Clear Lifecycle Management**
- EventBroker is created during application startup from router's broker
- Proper cleanup during shutdown
- Clear initialization order
- Fallback to basic EventBroker if needed

### 4. **Type Safety**
- Full type hints and IDE support
- Clear dependency relationships
- Compile-time error detection

### 5. **Flexibility**
- Easy to swap implementations
- Support for different environments (test, dev, prod)
- Configuration-driven dependency injection

## Migration Guide

### Step 1: Fix router issues
Remove undefined variables and simplify router creation.

### Step 2: Update main.py
Add lifespan management that creates EventBroker from router's broker.

### Step 3: Update dependency functions
Replace global variables with application state.

### Step 4: Use type aliases
Create reusable type aliases for common dependencies.

### Step 5: Update service constructors
Use the new dependency patterns consistently.

### Step 6: Update tests
Use FastAPI's dependency override system for testing.

## Best Practices

1. **Use FastAPI's built-in dependency system** - it's designed for this
2. **Share broker instances** - avoid connection duplication
3. **Keep dependencies explicit** - avoid hidden global state
4. **Use type hints consistently** for better IDE support
5. **Test with mocks** using dependency overrides
6. **Initialize expensive resources once** during application startup
7. **Clean up resources** during application shutdown

## Example Usage

```python
# In your route handlers
@router.post("/agents")
async def create_agent(
    agent_data: AgentCreate,
    agent_service: Annotated[AgentService, Depends(get_agent_service)]
):
    return await agent_service.create_agent(**agent_data.dict())

# The EventBroker is automatically injected through the dependency chain:
# get_agent_service -> EventBrokerDep -> get_event_broker -> app_state.event_broker
# And app_state.event_broker uses the same Redis broker as the FastStream router!
```

## Verification

You can verify that the EventBroker uses the same broker instance as the router:

```python
from agentarea.api.events.events_router import router as events_router
from agentarea.common.events.router import create_event_broker_from_router

event_broker = create_event_broker_from_router(events_router)
print(f"Router broker: {type(events_router.broker)}")
print(f"EventBroker redis_broker: {type(event_broker.redis_broker)}")
# They share the same underlying RedisBroker instance!
```

This approach follows Python best practices and makes your code more maintainable, testable, and robust while ensuring your EventBroker and FastStream router share the same underlying broker connection. 