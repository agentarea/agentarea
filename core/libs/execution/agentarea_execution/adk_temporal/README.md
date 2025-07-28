# ADK-Temporal Integration

This package provides seamless integration between Google's Agent Development Kit (ADK) and Temporal workflows, enabling ADK agents to run with Temporal's durability, scalability, and workflow capabilities while preserving all ADK interfaces.

## Overview

The ADK-Temporal integration allows you to:

- **Run ADK agents as Temporal activities**: Every LLM call and tool execution becomes a Temporal activity
- **Preserve all ADK interfaces**: Existing ADK code works without modification  
- **Gain workflow durability**: Pause, resume, and inspect agent execution at any point
- **Stream events in real-time**: Maintain ADK's event streaming for live UI updates
- **Scale reliably**: Leverage Temporal's distributed execution capabilities

## Architecture

```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│   ADK Agent         │    │  Temporal Workflow  │    │  Temporal Activity  │
│                     │    │                     │    │                     │
│  ┌─────────────┐    │    │  ┌─────────────┐    │    │  ┌─────────────┐    │
│  │ LlmAgent    │────┼────┼──│ ADKAgent    │────┼────┼──│ execute_adk │    │
│  │             │    │    │  │ Workflow    │    │    │  │ _agent      │    │
│  └─────────────┘    │    │  └─────────────┘    │    │  └─────────────┘    │
│                     │    │                     │    │                     │
│  ┌─────────────┐    │    │  Event Streaming    │    │  Service Bridges    │
│  │ Tools       │    │    │  State Management   │    │  Event Serialization│
│  │ Memory      │    │    │  Pause/Resume       │    │  Error Handling     │
│  │ Sessions    │    │    │  Observability      │    │                     │
│  └─────────────┘    │    │                     │    │                     │
└─────────────────────┘    └─────────────────────┘    └─────────────────────┘
```

## Key Components

### 1. Workflows
- **`ADKAgentWorkflow`**: Main workflow that orchestrates agent execution
- Handles initialization, validation, execution, and finalization
- Supports pause/resume, state queries, and event streaming

### 2. Activities  
- **`execute_adk_agent_activity`**: Executes complete ADK agent runs
- **`validate_adk_agent_config`**: Validates agent configurations
- **`stream_adk_agent_activity`**: Streaming variant for real-time execution

### 3. Service Bridges
- **`TemporalSessionService`**: Session management within workflow state
- Uses ADK's in-memory services by default for simplicity
- Extensible for external storage integration

### 4. Utilities
- **`EventSerializer`**: Converts ADK Events to/from Temporal-serializable dicts
- **`AgentBuilder`**: Creates ADK agents from configuration dictionaries

## Quick Start

### 1. Basic Agent Execution

```python
from adk_temporal import execute_adk_agent_activity
from adk_temporal.utils.agent_builder import create_simple_agent_config
from adk_temporal.services.adk_service_factory import create_default_session_data

# Create agent configuration
agent_config = create_simple_agent_config(
    name="my_agent",
    model="gpt-4", 
    instructions="You are a helpful assistant",
    description="My test agent"
)

# Create session data
session_data = create_default_session_data(user_id="test_user")

# Create user message
user_message = {
    "content": "Hello, please help me with a task",
    "role": "user"
}

# Execute agent
events = await execute_adk_agent_activity(
    agent_config,
    session_data, 
    user_message
)

print(f"Agent generated {len(events)} events")
```

### 2. Workflow Execution

```python
from temporalio.client import Client
from adk_temporal.workflows.adk_agent_workflow import ADKAgentWorkflow
from agentarea_execution.models import AgentExecutionRequest

# Connect to Temporal
client = await Client.connect("localhost:7233")

# Create execution request  
request = AgentExecutionRequest(
    task_id=uuid4(),
    agent_id=uuid4(),
    task_query="Explain quantum computing",
    task_parameters={},
    requires_human_approval=False,
    budget_usd=10.0
)

# Start workflow
workflow_handle = await client.start_workflow(
    ADKAgentWorkflow.run,
    request,
    id=f"agent-{request.task_id}",
    task_queue="agent-queue"
)

# Wait for result
result = await workflow_handle.result()
print(f"Success: {result.success}")
print(f"Response: {result.final_response}")
```

### 3. Workflow Control

```python
# Pause workflow
await workflow_handle.signal(ADKAgentWorkflow.pause, "Manual pause")

# Query current state
state = await workflow_handle.query(ADKAgentWorkflow.get_current_state)
print(f"Events: {state['event_count']}, Paused: {state['paused']}")

# Resume workflow  
await workflow_handle.signal(ADKAgentWorkflow.resume, "Continue processing")

# Get events
events = await workflow_handle.query(ADKAgentWorkflow.get_events, 10)
```

## Configuration

### Agent Configuration

```python
agent_config = {
    "name": "my_agent",              # Required: Agent identifier
    "model": "gpt-4",                # LLM model to use
    "instructions": "System prompt", # Agent instructions
    "description": "Agent purpose",  # Human-readable description
    "tools": [                       # Optional: Tool definitions
        {
            "name": "calculator",
            "description": "Math operations"
        }
    ]
}
```

### Session Configuration

```python
session_data = {
    "user_id": "user123",           # User identifier
    "session_id": "session456",     # Session identifier  
    "app_name": "my_app",           # Application name
    "state": {}                     # Initial session state
}
```

## Testing

Run the test suite:

```bash
# Unit tests
pytest adk_temporal/tests/test_event_serializer.py
pytest adk_temporal/tests/test_agent_builder.py
pytest adk_temporal/tests/test_adk_activities.py
pytest adk_temporal/tests/test_adk_workflow.py

# Integration tests
pytest adk_temporal/tests/test_integration.py

# All tests
pytest adk_temporal/tests/
```

## Examples

See `example_usage.py` for comprehensive examples including:

- Simple agent execution
- Workflow execution with Temporal server
- Agent configuration validation
- Workflow pause/resume control
- Error handling patterns

## Benefits

### 1. **Zero ADK Modification**
- All existing ADK interfaces preserved
- Drop-in replacement for ADK runners
- Gradual migration path

### 2. **Full Temporal Benefits**
- Durable execution across failures
- Pause/resume capability  
- Complete observability
- Distributed scalability

### 3. **Event Streaming**
- Real-time event delivery
- UI updates during execution
- Complete conversation history

### 4. **Production Ready**
- Comprehensive error handling
- Activity retries and timeouts
- Workflow state management
- Cost tracking and budgets

## Integration with AgentArea

This integration is designed to work seamlessly with AgentArea's existing infrastructure:

- **Task Management**: Execute agents for AgentArea tasks
- **Agent Registry**: Load agent configurations from AgentArea database  
- **MCP Integration**: Tool execution through AgentArea's MCP infrastructure
- **Event System**: Publish workflow events to AgentArea's event bus
- **UI Updates**: Real-time agent execution status in AgentArea frontend

## Limitations and Future Work

### Current Limitations
- Uses in-memory services (can be extended for persistence)
- Basic tool integration (MCP bridge can be enhanced)
- Single-agent workflows (multi-agent orchestration planned)

### Future Enhancements
- **Enhanced MCP Integration**: Full tool discovery and execution
- **Multi-Agent Workflows**: Hierarchical agent coordination  
- **Advanced Streaming**: Real-time event delivery to UI
- **Cost Optimization**: LLM call batching and caching
- **Service Integration**: External memory and artifact storage

## Contributing

1. Follow existing code patterns and ADK interfaces
2. Add comprehensive tests for new functionality
3. Update documentation for API changes
4. Ensure compatibility with existing ADK code

## Architecture Notes

The integration maintains a clear separation between ADK and Temporal concerns:

- **ADK Layer**: Unchanged agent, tool, and service interfaces
- **Bridge Layer**: Serialization, service adaptation, and state management  
- **Temporal Layer**: Workflow orchestration, durability, and scaling

This design ensures that ADK functionality remains intact while gaining all Temporal benefits.