# ADK-Temporal Integration: Temporal as Execution Backbone

This module provides seamless integration between Google's Agent Development Kit (ADK) and Temporal workflows, making Temporal the backbone for tool and LLM execution while keeping the ADK library mostly untouched.

## Architecture Overview

```
┌─────────────────┐    ┌──────────────────┐    ┌─────────────────┐
│   ADK Agent     │    │  Temporal        │    │   Activities    │
│                 │    │  Workflow        │    │                 │
│  ┌───────────┐  │    │                  │    │  ┌───────────┐  │
│  │ LLM Calls │──┼────┼──────────────────┼────┼──│ LLM       │  │
│  └───────────┘  │    │                  │    │  │ Activity  │  │
│                 │    │                  │    │  └───────────┘  │
│  ┌───────────┐  │    │                  │    │                 │
│  │Tool Calls │──┼────┼──────────────────┼────┼──┌───────────┐  │
│  └───────────┘  │    │                  │    │  │ Tool      │  │
│                 │    │                  │    │  │ Activity  │  │
└─────────────────┘    └──────────────────┘    │  └───────────┘  │
                                               └─────────────────┘
```

## Key Components

### 1. Temporal LLM Service (`temporal_llm_service.py`)

Intercepts ADK LLM calls and routes them through Temporal activities:

```python
from agentarea_execution.adk_temporal.services.temporal_llm_service import TemporalLlmService

# LLM calls automatically routed through Temporal
llm_service = TemporalLlmService(model="gpt-4", agent_config=config, session_data=session)
```

**Features:**
- ✅ Transparent LLM call interception
- ✅ OpenAI-compatible message format conversion
- ✅ Tool call support
- ✅ Usage tracking and cost calculation
- ✅ Error handling with fallback responses

### 2. Temporal Tool Service (`temporal_tool_service.py`)

Routes ADK tool calls through Temporal activities:

```python
from agentarea_execution.adk_temporal.services.temporal_tool_service import TemporalTool

# Tool calls automatically routed through Temporal
tool = TemporalTool(name="calculator", description="Math tool", server_instance_id=server_id)
```

**Features:**
- ✅ MCP tool integration
- ✅ Function declaration support
- ✅ Long-running tool support
- ✅ Tool discovery from agent configuration
- ✅ Error handling and retry logic

### 3. Enhanced Service Factory (`adk_service_factory.py`)

Creates ADK runners with Temporal backbone:

```python
from agentarea_execution.adk_temporal.services.adk_service_factory import create_adk_runner

# Create runner with Temporal backbone enabled
runner = create_adk_runner(
    agent_config=config,
    session_data=session,
    use_temporal_backbone=True  # Enable Temporal routing
)
```

### 4. Enhanced Agent Builder (`agent_builder.py`)

Builds ADK agents with Temporal-enhanced services:

```python
from agentarea_execution.adk_temporal.utils.agent_builder import build_temporal_enhanced_agent

# Build agent with Temporal services integrated
agent = build_temporal_enhanced_agent(agent_config, session_data)
```

## Usage Examples

### Basic Integration

```python
import asyncio
from temporalio import workflow
from agentarea_execution.adk_temporal.services.adk_service_factory import create_adk_runner

@workflow.defn
class MyAgentWorkflow:
    @workflow.run
    async def run(self, agent_config, session_data, user_message):
        # Create runner with Temporal backbone
        runner = create_adk_runner(
            agent_config=agent_config,
            session_data=session_data,
            use_temporal_backbone=True
        )
        
        # Execute agent - tool/LLM calls go through Temporal
        events = []
        async for event in runner.run_async(
            user_id=session_data["user_id"],
            session_id=session_data["session_id"],
            new_message=user_message
        ):
            events.append(event)
            if event.is_final_response():
                break
        
        return {"events": events}
```

### Advanced Workflow Integration

```python
@workflow.defn
class AdvancedAgentWorkflow:
    @workflow.run
    async def run(self, request):
        # Step 1: Build agent configuration
        agent_config = await workflow.execute_activity(
            build_agent_config_activity,
            args=[request.agent_id],
            start_to_close_timeout=60
        )
        
        # Step 2: Execute with Temporal backbone
        events = await workflow.execute_activity(
            execute_agent_step,
            args=[agent_config, request.session_data, request.message],
            start_to_close_timeout=600
        )
        
        # Step 3: Process results
        return self.process_events(events)
```

## Benefits

### 🚀 **Workflow Orchestration**
- Complex multi-step agent workflows
- Conditional execution based on results
- Parallel agent execution
- Workflow state persistence

### 🔄 **Reliability & Resilience**
- Automatic retries for failed tool/LLM calls
- Workflow recovery from failures
- Timeout handling
- Circuit breaker patterns

### 📊 **Observability**
- Complete execution history
- Tool and LLM call tracing
- Performance metrics
- Cost tracking

### 🎯 **Scalability**
- Horizontal scaling of agent execution
- Load balancing across workers
- Resource management
- Queue-based execution

### 🔧 **Flexibility**
- Easy A/B testing of different models
- Dynamic tool configuration
- Runtime agent modification
- Multi-tenant support

## Configuration

### Agent Configuration

```python
agent_config = {
    "name": "my_agent",
    "model_id": "gpt-4",  # Can be UUID or model name
    "instruction": "You are a helpful assistant",
    "description": "Agent with Temporal backbone",
    "tools_config": {
        "mcp_servers": ["server-uuid-1", "server-uuid-2"]
    }
}
```

### Session Configuration

```python
session_data = {
    "user_id": "user123",
    "session_id": "session456",
    "app_name": "my_app",
    "state": {}  # Optional initial state
}
```

## Running the Example

1. **Start Temporal Server:**
   ```bash
   temporal server start-dev
   ```

2. **Run Worker:**
   ```bash
   cd core/libs/execution
   python -m agentarea_execution.adk_temporal.examples.temporal_backbone_example worker
   ```

3. **Run Example:**
   ```bash
   cd core/libs/execution
   python -m agentarea_execution.adk_temporal.examples.temporal_backbone_example
   ```

## Integration Points

### ADK Integration
- **LLM Registry**: Temporal LLM service registered with ADK's LLM registry
- **Tool System**: Temporal tools implement ADK's BaseTool interface
- **Agent Builder**: Enhanced builder creates agents with Temporal services
- **Event System**: ADK events serialized for Temporal storage

### Temporal Integration
- **Activities**: Tool and LLM calls as Temporal activities
- **Workflows**: Agent execution orchestrated by workflows
- **State Management**: Workflow state persists agent context
- **Error Handling**: Temporal's retry and error handling

## Migration Guide

### From Direct ADK Usage

**Before:**
```python
# Direct ADK usage
agent = LlmAgent(name="my_agent", model="gpt-4", tools=tools)
runner = Runner(agent=agent, ...)

async for event in runner.run_async(...):
    # Process events
```

**After:**
```python
# With Temporal backbone
agent_config = {"name": "my_agent", "model": "gpt-4", "tools": tool_configs}
runner = create_adk_runner(agent_config, session_data, use_temporal_backbone=True)

async for event in runner.run_async(...):
    # Same event processing - tool/LLM calls now go through Temporal
```

### From Temporal Activities

**Before:**
```python
# Manual activity orchestration
@workflow.defn
class MyWorkflow:
    async def run(self):
        llm_result = await workflow.execute_activity(call_llm_activity, ...)
        tool_result = await workflow.execute_activity(execute_tool_activity, ...)
        # Manual orchestration
```

**After:**
```python
# ADK handles orchestration, Temporal handles execution
@workflow.defn
class MyWorkflow:
    async def run(self):
        events = await workflow.execute_activity(execute_agent_step, ...)
        # ADK orchestrates, Temporal executes
```

## Best Practices

1. **Use Temporal Backbone for Production**: Enable `use_temporal_backbone=True` for production workloads
2. **Configure Timeouts**: Set appropriate timeouts for long-running operations
3. **Handle Errors Gracefully**: Implement proper error handling in workflows
4. **Monitor Performance**: Use Temporal's observability features
5. **Test Thoroughly**: Test both ADK functionality and Temporal integration

## Troubleshooting

### Common Issues

1. **LLM Service Not Registered**
   ```python
   # Ensure registration happens before agent creation
   TemporalLlmServiceFactory.register_with_adk()
   ```

2. **Tool Discovery Fails**
   ```python
   # Check agent configuration has proper tool setup
   agent_config["tools_config"] = {"mcp_servers": [server_id]}
   ```

3. **Workflow Timeouts**
   ```python
   # Increase timeouts for long-running operations
   await workflow.execute_activity(
       activity,
       start_to_close_timeout=600  # 10 minutes
   )
   ```

## Future Enhancements

- [ ] Streaming LLM responses through Temporal
- [ ] Advanced tool chaining workflows
- [ ] Multi-agent collaboration patterns
- [ ] Dynamic model switching
- [ ] Cost optimization strategies
- [ ] Enhanced observability dashboards

This integration provides the best of both worlds: ADK's rich agent capabilities with Temporal's robust workflow orchestration and execution reliability.