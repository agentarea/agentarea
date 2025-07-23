# Service Patterns

AgentArea follows a layered service architecture with clear separation of concerns.

## Base Service Pattern

**Location**: `agentarea_common.base.service`

```python
class BaseCrudService(Generic[T]):
    def __init__(self, repository: BaseRepository[T]):
        self.repository = repository
    
    # Provides basic CRUD operations that delegate to repository
    async def get(self, id: UUID) -> T | None
    async def list(self) -> list[T] 
    async def create(self, entity: T) -> T
    async def update(self, entity: T) -> T
    async def delete(self, id: UUID) -> bool
```

## Domain Service Implementation

Services extend the base and add domain-specific business logic:

```python
class AgentService(BaseCrudService[Agent]):
    def __init__(self, repository: AgentRepository, event_broker: EventBroker):
        super().__init__(repository)
        self.event_broker = event_broker
    
    async def create_agent(self, name: str, description: str, ...) -> Agent:
        # 1. Create domain entity
        agent = Agent(name=name, description=description, ...)
        
        # 2. Persist via repository
        agent = await self.create(agent)
        
        # 3. Publish domain event
        await self.event_broker.publish(AgentCreated(...))
        
        return agent
```

## Service Layer Responsibilities

1. **Business Logic**: Domain-specific rules and validations
2. **Event Publishing**: Emit domain events after state changes
3. **Transaction Management**: Coordinate multiple repository operations
4. **API Translation**: Convert between API models and domain entities

## Dependency Injection

Services receive dependencies via constructor injection:
- Repository for data access
- EventBroker for domain events  
- Other services for cross-domain operations