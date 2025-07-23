# Dependency Injection Patterns

AgentArea uses a centralized DI container pattern for service management across all libraries.

## DI Container Design

**Location**: `agentarea_common.di.container`

The `DIContainer` class provides:
- `register_singleton(interface, instance)` - Register singleton instances
- `register_factory(interface, factory)` - Register factory functions
- `get(interface)` - Retrieve instances (singletons first, then factory-created singletons)
- `clear()` - Clear registrations (useful for testing)

**Key Features**:
- Factory-created instances are stored as singletons automatically
- Type-safe with generic type parameters
- Simple interface-based registration

## Integration Pattern

Each library has its own DI container setup in `infrastructure/di_container.py`:

```python
def initialize_di_container() -> DIContainer:
    container = DIContainer()
    # Register services, repositories, etc.
    return container

def get_di_container() -> DIContainer:
    # Return singleton container instance
    
def get_service_name() -> ServiceType:
    # Convenience functions for common services
```

## Usage in Services

Services receive their dependencies through constructor injection:

```python
class AgentService(BaseCrudService[Agent]):
    def __init__(self, repository: AgentRepository, event_broker: EventBroker):
        super().__init__(repository)
        self.event_broker = event_broker
```

The DI container manages the lifecycle and wiring of these dependencies.