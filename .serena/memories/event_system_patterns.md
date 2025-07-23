# Event System Patterns

AgentArea uses a Redis-based event system for inter-service communication.

## Core Event Architecture

### Base Event Structure

**Location**: `agentarea_common.events.base_events`

```python
@dataclass
class DomainEvent:
    event_id: UUID
    timestamp: datetime
    event_type: str  # Auto-set to class name
    data: dict[str, Any]
```

### Event Broker Interface

**Location**: `agentarea_common.events.broker`

```python
class EventBroker(ABC):
    @abstractmethod
    async def publish(self, event: DomainEvent) -> None:
        raise NotImplementedError
```

### Redis Implementation

**Location**: `agentarea_common.events.redis_event_broker`

```python
class RedisEventBroker(EventBroker):
    def __init__(self, redis_broker: RedisBroker)
    async def publish(self, event: DomainEvent)
    # Auto-connects, publishes to event-type channels
    # Supports async context manager
```

## Domain Events

Each domain defines its own events (e.g., in `agents/domain/events.py`):

```python
class AgentCreated(DomainEvent):
class AgentUpdated(DomainEvent): 
class AgentDeleted(DomainEvent):
```

## Service Integration

Services publish events after domain operations:

```python
async def create_agent(...) -> Agent:
    agent = await self.create(agent)
    await self.event_broker.publish(
        AgentCreated(agent_id=agent.id, name=agent.name, ...)
    )
    return agent
```

## Event Routing

Events are published to Redis channels named after their event_type (class name).