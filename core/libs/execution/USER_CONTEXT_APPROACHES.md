# User Context Handling in Temporal Workers

## The Problem
When Temporal activities execute asynchronously in worker processes, they don't have access to the original user's request context. However, we need to maintain proper data isolation and security by ensuring activities only access data the user is authorized to see.

## Approach 1: Pass User Context Through Parameters ⭐ (Recommended)

**Concept**: Include user context as serializable data in workflow/activity parameters.

### Pros:
- ✅ **Explicit and traceable** - user context is visible in Temporal UI
- ✅ **Secure** - no shared state, each execution has its own context
- ✅ **Auditable** - can see exactly which user context was used for each activity
- ✅ **Scalable** - works across multiple workers and machines
- ✅ **Temporal-native** - follows Temporal best practices

### Cons:
- ❌ Requires updating all activity signatures
- ❌ Slightly more verbose parameter passing

### Implementation:

```python
# In workflow
user_context_data = {
    "user_id": request.user_id,
    "workspace_id": request.workspace_id,
    "roles": request.user_roles
}

agent_config = await workflow.execute_activity(
    Activities.BUILD_AGENT_CONFIG,
    args=[agent_id, user_context_data],
    # ... other params
)

# In activity
@activity.defn
async def build_agent_config_activity(
    agent_id: UUID,
    user_context_data: dict[str, Any]
) -> dict[str, Any]:
    user_context = UserContext(**user_context_data)
    agent_repository = AgentRepository(session, user_context)
    # ... rest of activity
```

---

## Approach 2: Activity-Level Context Injection

**Concept**: Use Temporal's activity context to store user information and inject it into repositories.

### Pros:
- ✅ **Clean activity signatures** - no extra parameters needed
- ✅ **Centralized** - context handling in one place
- ✅ **Flexible** - can be applied to any activity

### Cons:
- ❌ **Less explicit** - context is "hidden" from activity signatures
- ❌ **Temporal-specific** - relies on Temporal's activity info mechanism
- ❌ **Debugging complexity** - harder to trace context in Temporal UI

### Implementation:

```python
# Enhanced activity dependencies with context extraction
class ActivityDependencies:
    def __init__(self, settings, event_broker, secret_manager):
        self.settings = settings
        self.event_broker = event_broker
        self.secret_manager = secret_manager
    
    def get_user_context(self) -> UserContext:
        """Extract user context from Temporal activity info."""
        try:
            activity_info = activity.info()
            # User context stored in workflow memo or search attributes
            memo = activity_info.workflow_memo
            return UserContext(
                user_id=memo.get("user_id", "system"),
                workspace_id=memo.get("workspace_id", "default"),
                roles=memo.get("roles", ["user"])
            )
        except:
            # Fallback for non-activity contexts
            return UserContext(user_id="system", workspace_id="default", roles=["admin"])

# In activity factory
def make_agent_activities(dependencies: ActivityDependencies):
    @activity.defn
    async def build_agent_config_activity(agent_id: UUID) -> dict[str, Any]:
        user_context = dependencies.get_user_context()
        async with get_database().async_session_factory() as session:
            agent_repository = AgentRepository(session, user_context)
            # ... rest of activity

# In workflow startup
handle = await client.start_workflow(
    AgentExecutionWorkflow.run,
    request,
    id=workflow_id,
    task_queue="agent-tasks",
    memo={
        "user_id": request.user_id,
        "workspace_id": request.workspace_id,
        "roles": request.user_roles
    }
)
```

---

## Approach 3: Repository Factory with Context Resolution

**Concept**: Create a repository factory that can resolve user context from multiple sources.

### Pros:
- ✅ **Backward compatible** - existing activities don't need changes
- ✅ **Flexible resolution** - can try multiple context sources
- ✅ **Centralized logic** - all context resolution in one place
- ✅ **Graceful fallbacks** - can handle missing context gracefully

### Cons:
- ❌ **Complex resolution logic** - multiple fallback mechanisms
- ❌ **Potential security gaps** - fallbacks might be too permissive
- ❌ **Hidden dependencies** - not clear what context is being used

### Implementation:

```python
class ContextAwareRepositoryFactory:
    """Factory that creates repositories with proper user context resolution."""
    
    def __init__(self, session: AsyncSession):
        self.session = session
    
    async def create_agent_repository(self) -> AgentRepository:
        """Create AgentRepository with resolved user context."""
        user_context = await self._resolve_user_context()
        return AgentRepository(self.session, user_context)
    
    async def _resolve_user_context(self) -> UserContext:
        """Resolve user context from multiple sources in priority order."""
        
        # Priority 1: From Temporal activity info (if available)
        try:
            activity_info = activity.info()
            if hasattr(activity_info, 'workflow_memo'):
                memo = activity_info.workflow_memo
                if memo and "user_id" in memo:
                    return UserContext(
                        user_id=memo["user_id"],
                        workspace_id=memo.get("workspace_id", "default"),
                        roles=memo.get("roles", ["user"])
                    )
        except:
            pass
        
        # Priority 2: From workflow search attributes
        try:
            # Could extract from workflow search attributes
            pass
        except:
            pass
        
        # Priority 3: From task metadata (if stored in task parameters)
        try:
            # Could extract from task creation metadata
            pass
        except:
            pass
        
        # Priority 4: System fallback (for system operations)
        logger.warning("Using system context fallback - ensure this is intentional")
        return UserContext(
            user_id="system",
            workspace_id="default",
            roles=["admin"]
        )

# Usage in activities
@activity.defn
async def build_agent_config_activity(agent_id: UUID) -> dict[str, Any]:
    async with get_database().async_session_factory() as session:
        repo_factory = ContextAwareRepositoryFactory(session)
        agent_repository = await repo_factory.create_agent_repository()
        # ... rest of activity
```

---

## Recommendation: Hybrid Approach

**Best Practice**: Combine Approach 1 (explicit parameters) with Approach 3 (factory fallbacks):

```python
@activity.defn
async def build_agent_config_activity(
    agent_id: UUID,
    user_context_data: dict[str, Any] | None = None  # Optional explicit context
) -> dict[str, Any]:
    async with get_database().async_session_factory() as session:
        if user_context_data:
            # Explicit context provided (preferred)
            user_context = UserContext(**user_context_data)
        else:
            # Fallback to context resolution
            repo_factory = ContextAwareRepositoryFactory(session)
            user_context = await repo_factory._resolve_user_context()
        
        agent_repository = AgentRepository(session, user_context)
        # ... rest of activity
```

This provides:
- **Security by default** - explicit context when available
- **Backward compatibility** - fallback resolution for existing code
- **Clear audit trail** - can see when explicit vs fallback context was used
- **Flexibility** - works in various execution environments

## Security Considerations

1. **Never use hardcoded "admin" context** in production
2. **Always validate workspace access** before returning data
3. **Log context resolution** for security auditing
4. **Fail securely** - if context can't be resolved, fail rather than use permissive defaults
5. **Consider context encryption** for sensitive user information in Temporal storage