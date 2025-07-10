# AgentArea Execution Library

This library provides Google ADK (Agent Development Kit) powered execution for AI agents using Temporal workflows. It integrates Google's official Agent Development Kit with AgentArea's workflow orchestration system.

## Architecture Overview

The execution library follows a clean architecture pattern with clear separation of concerns:

- **Domain**: Core business entities and rules
- **Workflows**: Temporal workflow definitions  
- **Services**: Application layer services
- **Infrastructure**: External system integrations

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
    activity_services: ActivityServicesInterface,
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