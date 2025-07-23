# Repository Patterns

AgentArea follows the Repository pattern with a clear abstraction layer.

## Base Repository Interface

**Location**: `agentarea_common.base.repository`

```python
class BaseRepository(ABC, Generic[T]):
    async def get(self, id: UUID) -> T | None
    async def list(self) -> list[T]
    async def create(self, entity: T) -> T
    async def update(self, entity: T) -> T
    async def delete(self, id: UUID) -> bool
```

## Implementation Pattern

Concrete repositories extend the base and implement domain-specific logic:

```python
class AgentRepository(BaseRepository[Agent]):
    def __init__(self, session: AsyncSession):
        self.session = session
    
    # Implements all abstract methods using SQLAlchemy async session
    # Uses select(), merge(), delete() patterns
    # Always calls flush() after mutations
```

## Key Conventions

1. **Async/Await**: All operations are asynchronous
2. **Session Management**: Repositories receive AsyncSession via constructor
3. **Generic Types**: Repositories are typed with their entity type
4. **SQLAlchemy Integration**: Uses modern SQLAlchemy async patterns
5. **Error Handling**: Returns None for not found, raises for errors

## Domain Models

All entities extend `BaseModel` which provides:
- UUID primary keys
- `created_at` and `updated_at` timestamps
- `to_dict()` helper method
- SQLAlchemy DeclarativeBase inheritance