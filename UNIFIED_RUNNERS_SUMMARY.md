# Unified Agent Runners Architecture

## Overview

We've successfully created a unified architecture for agent execution runners that provides consistent interfaces while supporting different execution environments (synchronous testing, Temporal workflows, etc.).

## Architecture

### Shared Location: `core/libs/execution/agentarea_execution/runners/`

All runners are now located in a shared module with unified interfaces:

```
core/libs/execution/agentarea_execution/runners/
├── __init__.py              # Exports all runners and base classes
├── base.py                  # Base classes and shared interfaces
├── sync_runner.py           # Synchronous runner for testing
└── temporal_runner.py       # Temporal workflow runner
```

### Base Classes and Interfaces

#### `BaseAgentRunner` (Abstract Base Class)
- Provides unified interface for all runners
- Implements shared termination logic via `ExecutionTerminator`
- Defines common execution loop pattern via `_execute_main_loop()`
- Ensures consistent behavior across different execution environments

#### Shared Data Classes
- `Message` - Structured conversation messages
- `AgentGoal` - Goal definition with success criteria
- `RunnerConfig` - Configuration for execution parameters
- `ExecutionResult` - Standardized execution results

#### `ExecutionTerminator`
- Unified termination condition checking
- Supports goal achievement, max iterations, and budget limits
- Respects goal-specific max_iterations over global config

### Runner Implementations

#### `SyncAgentRunner`
- **Purpose**: Testing and framework-agnostic execution
- **Dependencies**: LLM client, tool executor, goal evaluator
- **Use Cases**: Unit tests, simple automation, development
- **Benefits**: No Temporal dependencies, easy mocking, fast execution

#### `TemporalAgentRunner`
- **Purpose**: Production workflow orchestration
- **Dependencies**: Temporal activities, event manager, budget tracker
- **Use Cases**: Production agent execution, complex workflows, monitoring
- **Benefits**: Durability, scalability, pause/resume, event tracking

## Unified Interface

Both runners implement the same core interface:

```python
# Create runner with configuration
config = RunnerConfig(max_iterations=10, temperature=0.1)
runner = SyncAgentRunner(llm_model, config=config)
# or
runner = TemporalAgentRunner(activities, config=config)

# Execute with same interface
goal = AgentGoal(
    description="Complete the task",
    success_criteria=["Task completed successfully"],
    max_iterations=5
)

result = await runner.run(goal)

# Same result format
print(f"Success: {result.success}")
print(f"Iterations: {result.current_iteration}")
print(f"Cost: ${result.total_cost}")
print(f"Response: {result.final_response}")
```

## Key Features

### 1. **Consistent Termination Logic**
- Goal achievement detection (highest priority)
- Maximum iterations enforcement (respects goal-specific limits)
- Budget constraint checking
- Unified across all runners

### 2. **Framework Agnostic Core**
- Base execution logic independent of infrastructure
- Easy to test without complex setup
- Reusable across different execution contexts

### 3. **Extensible Architecture**
- Easy to add new runner types (e.g., AsyncRunner, BatchRunner)
- Shared termination and configuration logic
- Consistent interfaces for tools and LLM integration

### 4. **Comprehensive Testing**
All runners tested with:
- Multi-iteration workflows
- Tool execution and error handling
- Goal evaluation and completion detection
- Maximum iteration limits
- Budget constraints

## Integration with Existing Workflow

The unified runners can be integrated into the existing `AgentExecutionWorkflow`:

```python
# In workflow
async def _execute_main_loop(self):
    # Create Temporal runner
    runner = TemporalAgentRunner(
        activities_interface=self.activities,
        event_manager=self.event_manager,
        budget_tracker=self.budget_tracker,
        config=RunnerConfig(max_iterations=25)
    )
    
    # Use unified interface
    goal = AgentGoal(
        description=self.state.goal.description,
        success_criteria=self.state.goal.success_criteria,
        max_iterations=self.state.goal.max_iterations
    )
    
    result = await runner.run(goal, workflow_state=self.state)
    return result
```

## Benefits Achieved

### ✅ **Clean Separation of Concerns**
- Orchestration logic in runners
- Infrastructure concerns in activities
- Business logic in services

### ✅ **Improved Testability**
- Framework-agnostic testing with SyncAgentRunner
- No Temporal setup required for unit tests
- Easy mocking and deterministic testing

### ✅ **Consistent Behavior**
- Same termination conditions across environments
- Unified configuration and result formats
- Predictable execution patterns

### ✅ **Framework Independence**
- Core agentic logic decoupled from Temporal
- Easy to port to other orchestration frameworks
- Reusable in different execution contexts

### ✅ **Maintainable Architecture**
- Single responsibility principle
- Clear interfaces and abstractions
- Easy to extend and modify

## Next Steps

1. **Update AgentExecutionWorkflow** to use TemporalAgentRunner
2. **Migrate existing tests** to use SyncAgentRunner
3. **Add more runner types** as needed (e.g., streaming, batch)
4. **Enhance goal evaluation** with more sophisticated methods
5. **Add performance monitoring** and metrics collection

## Conclusion

The unified runner architecture successfully provides:
- ✅ **Consistent interfaces** across execution environments
- ✅ **Framework-agnostic core** for better testability
- ✅ **Shared termination logic** for predictable behavior
- ✅ **Clean separation** between orchestration and infrastructure
- ✅ **Extensible design** for future requirements

This foundation makes the codebase more maintainable, testable, and easier to extend while preserving all the benefits of the existing Temporal-based infrastructure.