# AgentArea Execution Library

This library provides Google ADK (Agent Development Kit) powered execution for AI agents using Temporal workflows. It integrates Google's official Agent Development Kit with AgentArea's workflow orchestration system.

## Architecture Overview

The execution library follows a clean architecture pattern with clear separation of concerns:

- **Domain**: Core business entities and rules
- **Workflows**: Temporal workflow definitions  
- **Services**: Application layer services
- **Infrastructure**: External system integrations

### Single LLM call boundary

[`LLMExecutionService`](agentarea_execution/llm_execution_service.py) owns model
and credential resolution, output-token limits, provider invocation, response
aggregation, and final usage/cost conversion. It accepts an explicit `UserContext`
and a scoped model-service loader; the database scope closes before generation.
It can run outside Temporal.

The service streams by default. Constructing it with `stream=False` selects the
SDK's nonstreamed completion method and emits no progress callbacks. Omitting a
chunk callback does not change provider mode. Both modes require configured
pricing and positive token usage before returning a successful `LLMCallResult`.

[`call_llm_activity`](agentarea_execution/activities/agent/llm.py)
binds task event callbacks, constructs the principal, and maps ordinary errors to
Temporal failures. Its heartbeat and cancellation behavior remain in the activity
adapter. The workflow still awaits one final activity result and owns retries,
checkpoints, and run-budget accounting.

Stream chunks are provisional progress, not workflow history or durable task
events. Retried activities can repeat progress; this boundary does not provide
exactly-once delivery. Final events use the existing workflow publication path.

Live `llm.call.chunk` payloads are cumulative snapshots, not deltas: `chunk`
holds accumulated text and `thinking` holds accumulated reasoning for one
`execution_id`/`iteration`. The empty final callback preserves both. The UI
replaces the corresponding part rather than appending the snapshot again.

### Interaction and completion

Task status is a business state, not the Temporal execution status. A task may
be `completed` while its workflow is still waiting for a follow-up. The immediate
`task.completed` event carries `execution_status: "waiting"`; `execution.finished`
marks actual closure. The REST feed follows execution closure, while A2A keeps
its turn-scoped completion boundary.

[`interaction.py`](agentarea_execution/interaction.py) resolves the run's return
channel. API task parameters can explicitly select a configured web return
channel, independently of the trigger that started the run:

```json
{
  "interaction": {
    "channel": "web",
    "allow_questions": true,
    "allow_approvals": true,
    "allow_a2ui": true
  }
}
```

`channel: "none"` disables interactive delivery. Background, scheduled, delegated,
and external-channel runs default to noninteractive unless a supported return
channel is explicitly configured. These flags describe available interaction;
they do not grant tool access or approval authority. A2UI also requires the
agent's A2UI setting.

Without a question channel or permission, `request_user_input` is not offered to
the model. The agent attempts the task autonomously with its available context
and tools. It may report `completion.outcome: "blocked"` when an indispensable
prerequisite remains missing; unavailable interaction alone does not block a
run. Mandatory approval is never bypassed.

Displaying A2UI alone does not create a required wait. To request a required
nonsecret form response, emit its surface and call `request_user_input` with
`surface_id` and typed `questions`. A declared action on that surface supplies
the answer context; unrelated actions and invalid answers cannot resume it.
Single-selection A2UI `ChoicePicker` lists are adapted to native `select`
answers. Secret fields must use the native input/vault route, not A2UI context.

A required request waits for its matching validated response. Its 30-minute
timeout ends the run as `blocked` without another model call. Cancelling a pending
task persists its cancelled state and closes the interaction feed; stopping a
follow-up listener does not undo an already completed turn. New workflow behavior
is guarded by the `channel-aware-interaction-v1` Temporal patch; continued runs
preserve their resolved capabilities and pending identities.

## Package Structure

```
agentarea_execution/
├── domain/
│   ├── models.py          # Core domain entities (Task, Workflow, Agent, etc.)
│   ├── events.py          # Domain events for state changes
│   └── interfaces.py      # Repository and service contracts
├── workflows/
│   ├── base.py           # Base workflow classes and patterns
│   ├── agent_workflows.py     # Agent orchestration workflows (TODO)
│   ├── automation_workflows.py # Business process workflows (TODO) 
│   └── collaboration_workflows.py # A2A communication workflows (TODO)
├── services/
│   ├── orchestration.py  # Workflow and agent orchestration services
│   ├── task_distribution.py   # Task assignment and load balancing (TODO)
│   ├── communication.py      # Agent-to-agent messaging (TODO)
│   └── monitoring.py         # Execution monitoring and metrics (TODO)
└── infrastructure/
    ├── temporal.py       # Temporal.io integration interfaces
    ├── messaging.py      # Message broker integrations (TODO)
    └── monitoring.py     # Monitoring infrastructure (TODO)
```

## Core Concepts

### Domain Models

- **Task**: Represents a unit of work to be executed by an agent
- **Workflow**: Represents a collection of related tasks and coordination logic
- **Agent**: Represents an AI agent capable of executing tasks
- **ExecutionContext**: Provides execution environment and shared state

### Workflow Patterns

- **BaseWorkflow**: Foundation for all workflow types with Temporal integration
- **StatefulWorkflow**: Workflows that maintain state across activities  
- **LongRunningWorkflow**: Workflows that may run for days/weeks with checkpoints

### Service Interfaces

- **WorkflowOrchestrationService**: Manages workflow lifecycle
- **AgentOrchestrationService**: Handles agent assignment and scaling
- **ResourceOrchestrationService**: Manages computational resources

## Usage Examples

### Creating a Task

```python
from agentarea_execution.domain.models import Task, TaskStatus, TaskPriority
from uuid import uuid4
from datetime import datetime

task = Task(
    id=uuid4(),
    name="Process customer data",
    description="Extract and validate customer information from uploaded file",
    goal_state="Customer data processed and validated",
    status=TaskStatus.PENDING,
    priority=TaskPriority.HIGH,
    mcp_tools=["filesystem", "data-validator"],
    context={"file_path": "/uploads/customers.csv"}
)
```

### Defining a Workflow

```python
from agentarea_execution.workflows.base import BaseWorkflow, WorkflowContext
from uuid import uuid4

class DataProcessingWorkflow(BaseWorkflow[str]):
    def get_workflow_id(self) -> str:
        return f"data-processing-{uuid4()}"
    
    async def run(self, context: WorkflowContext, **kwargs) -> str:
        # Workflow implementation would go here
        # This is just an interface stub
        pass
```

### Using Services

```python
from agentarea_execution.services.orchestration import WorkflowOrchestrationService

# Service implementations would be injected via dependency injection
async def start_data_processing(
    workflow_service: WorkflowOrchestrationService,
    workflow_id: UUID
):
    success = await workflow_service.start_workflow(
        workflow_id=workflow_id,
        context={"source": "user_upload"}
    )
    return success
```

## Integration with AgentArea Platform

This execution library integrates with other AgentArea components:

- **MCP Integration**: Tasks can specify required MCP servers and tools
- **Agent Management**: Leverages agent repository for capability matching
- **Event System**: Publishes domain events for other services to consume
- **Resource Management**: Coordinates with infrastructure for scaling

## Implementation Status

- ✅ Domain models and interfaces
- ✅ Base workflow patterns  
- ✅ Temporal integration interfaces
- ✅ Orchestration service interfaces
- 🚧 Workflow implementations (TODO)
- 🚧 Service implementations (TODO)
- 🚧 Infrastructure implementations (TODO)

## Next Steps

1. Implement concrete workflow classes for common patterns
2. Create service implementations using existing AgentArea infrastructure
3. Integrate with Temporal.io SDK for durable execution
4. Add comprehensive test coverage
5. Create example workflows for key use cases

## Google ADK Integration

This library uses Google's official Agent Development Kit (ADK) **directly** with **no adapters**:

### Key Features

- ✅ **Direct Google ADK Integration**: Uses `google-adk` library with no adapter layer
- ✅ **Real MCP Tools**: Converts AgentArea MCP tools to Google ADK tool functions
- ✅ **Clean Architecture**: No hardcoded tools or unnecessary abstractions
- ✅ **Agent Creation**: Proper agent instances using real agent configuration
- ✅ **Temporal Workflows**: Integrated with Temporal for durable execution
- ✅ **Error Handling**: Comprehensive error handling and retry mechanisms

### Quick Start

1. Install dependencies:
```bash
pip install google-adk temporalio pydantic
```

2. Set up environment variables:
```bash
# For Google AI Studio (Gemini)
export GOOGLE_GENAI_USE_VERTEXAI=FALSE
export GOOGLE_API_KEY=your_api_key_here

# For Ollama/local models
export OLLAMA_BASE_URL=http://localhost:11434
```

3. Run integration test:
```bash
python test_google_adk.py
```

### Direct Usage Pattern

```python
# In Temporal activities - use Google ADK directly
from google.adk.agents import Agent

@activity.defn
async def execute_agent_task_activity(
    request: AgentExecutionRequest,
    available_tools: List[Dict[str, Any]],
    activity_services: ActivityDependencies,
) -> Dict[str, Any]:
    # 1. Get real agent config from AgentArea
    agent_config = await activity_services.agent_service.build_agent_config(request.agent_id)
    
    # 2. Convert MCP tools to ADK tool functions
    adk_tools = [create_adk_tool_from_mcp(tool, activity_services) for tool in available_tools]
    
    # 3. Create Google ADK agent directly
    agent = Agent(
        name=agent_config["name"],
        model=agent_config["model"],  # e.g., "gemini-2.0-flash" or "ollama_chat/qwen2.5"
        description=agent_config["description"],
        instruction=agent_config["instruction"],
        tools=adk_tools,  # Real MCP tools, not hardcoded ones
    )
    
    # 4. Execute using Google ADK session management
    return execution_result
```

### Why No Adapters?

- **Cleaner Code**: Direct usage is simpler and more maintainable
- **Real Tools**: Uses actual MCP tools from AgentArea, not hardcoded test tools
- **Less Abstraction**: Follows Google ADK patterns directly
- **Better Performance**: No extra layers of abstraction

## Dependencies

- **google-adk** (Google Agent Development Kit)
- **temporalio** (Temporal.io Python SDK for workflow execution)
- **pydantic** (Data validation and settings management)
- **httpx** (HTTP client for API calls)
- AgentArea Common (for shared infrastructure)
- AgentArea MCP (for tool integration)
- AgentArea Agents (for agent management) 