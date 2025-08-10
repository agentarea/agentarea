# Activity Dependency Injection Refactoring

## Problem

The original activity implementation had several issues:

1. **Manual session management** - Each activity manually created database sessions
2. **Service reconstruction** - Services were rebuilt from scratch in every activity  
3. **Context reconstruction** - UserContext was manually reconstructed from dictionaries
4. **No proper DI** - No dependency injection pattern, just manual instantiation
5. **Not Pythonic** - Verbose, error-prone, and hard to maintain

## Before (Old Pattern)

```python
@activity.defn
async def build_agent_config_activity(
    agent_id: UUID,
    user_context_data: dict[str, Any],
) -> dict[str, Any]:
    """Build agent configuration."""
    # Manual session creation
    database = get_database()
    async with database.async_session_factory() as session:
        # Manual context reconstruction
        user_context = UserContext(
            user_id=user_context_data["user_id"], 
            workspace_id=user_context_data["workspace_id"]
        )

        # Manual service creation
        repository_factory = RepositoryFactory(session, user_context)
        agent_service = AgentService(
            repository_factory=repository_factory, 
            event_broker=dependencies.event_broker
        )

        # Business logic
        agent = await agent_service.get(agent_id)
        # ... rest of logic
```

**Problems:**
- 8+ lines of boilerplate per activity
- Manual session lifecycle management
- Easy to forget session cleanup
- Repetitive service instantiation
- Hard to test and mock

## After (New Pattern)

```python
@activity.defn
async def build_agent_config_activity(
    agent_id: UUID,
    user_context_data: dict[str, Any],
) -> dict[str, Any]:
    """Build agent configuration."""
    user_context = create_user_context(user_context_data)
    
    async with ActivityContext(container, user_context) as ctx:
        agent_service = await ctx.get_agent_service()
        
        # Business logic
        agent = await agent_service.get(agent_id)
        # ... rest of logic
```

**Benefits:**
- 3 lines of setup vs 8+ lines
- Automatic session management and cleanup
- Clean service access through DI container
- Easy to test and mock
- Pythonic context manager pattern

## Architecture

### ActivityServiceContainer
- Central service factory
- Manages database sessions
- Provides clean service access
- Handles dependency injection

### ActivityContext
- Context manager for activity execution
- Automatic session cleanup and transaction management
- Auto-commit on success, auto-rollback on exceptions
- Service caching within context
- Proper resource management

### Helper Functions
- `create_user_context()` - Clean context creation
- `create_system_context()` - System context for background tasks

## Key Improvements

1. **Separation of Concerns** - Activities focus on business logic, not infrastructure
2. **Resource Management** - Automatic session cleanup and transaction management
3. **Transaction Safety** - Auto-commit on success, auto-rollback on exceptions
4. **Testability** - Easy to mock services through DI container
5. **Maintainability** - Less boilerplate, cleaner code
6. **Consistency** - Standardized pattern across all activities
7. **Error Handling** - Proper cleanup and rollback even on exceptions

## Usage Examples

### User Context Activity
```python
@activity.defn
async def user_activity(user_context_data: dict[str, Any]) -> dict:
    user_context = create_user_context(user_context_data)
    
    async with ActivityContext(container, user_context) as ctx:
        service = await ctx.get_agent_service()
        return await service.do_something()
```

### System Context Activity
```python
@activity.defn
async def system_activity(workspace_id: str) -> dict:
    user_context = create_system_context(workspace_id)
    
    async with ActivityContext(container, user_context) as ctx:
        service = await ctx.get_mcp_server_instance_service()
        return await service.do_something()
```

### Multiple Services
```python
@activity.defn
async def complex_activity(user_context_data: dict[str, Any]) -> dict:
    user_context = create_user_context(user_context_data)
    
    async with ActivityContext(container, user_context) as ctx:
        agent_service = await ctx.get_agent_service()
        model_service = await ctx.get_model_instance_service()
        
        # Use both services
        agent = await agent_service.get(agent_id)
        model = await model_service.get(model_id)
        
        return {"agent": agent, "model": model}
```

### Manual Transaction Control
```python
@activity.defn
async def transactional_activity(user_context_data: dict[str, Any]) -> dict:
    user_context = create_user_context(user_context_data)
    
    # Disable auto-commit for manual control
    async with ActivityContext(container, user_context, auto_commit=False) as ctx:
        service = await ctx.get_task_event_service()
        
        try:
            # Do some work
            await service.create_workflow_event(...)
            
            # Manually commit when ready
            await ctx.commit()
            
            return {"status": "success"}
        except Exception as e:
            # Manually rollback on error
            await ctx.rollback()
            raise
```

## Migration Guide

1. **Import new dependencies**:
   ```python
   from .dependencies import ActivityServiceContainer, create_user_context, ActivityContext
   ```

2. **Create container in factory**:
   ```python
   container = ActivityServiceContainer(dependencies)
   ```

3. **Replace manual session creation**:
   ```python
   # Old
   database = get_database()
   async with database.async_session_factory() as session:
       user_context = UserContext(...)
       repository_factory = RepositoryFactory(session, user_context)
       service = SomeService(repository_factory, ...)
   
   # New
   user_context = create_user_context(user_context_data)
   async with ActivityContext(container, user_context) as ctx:
       service = await ctx.get_some_service()
   ```

4. **Update service access**:
   ```python
   # Old
   agent_service = AgentService(repository_factory, event_broker)
   
   # New
   agent_service = await ctx.get_agent_service()
   ```

This refactoring makes activities much cleaner and more maintainable while following Python best practices for dependency injection and resource management.