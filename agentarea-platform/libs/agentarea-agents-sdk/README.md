# AgentArea Agents SDK

Independent Agent SDK for AgentArea - agentic AI components with no internal dependencies.

## Overview

This SDK contains the core agentic AI components extracted from the main AgentArea platform:

- **LLM Models**: Unified interface for multiple LLM providers (OpenAI, Claude, Ollama, etc.)
- **Agent Tools**: Extensible tool system with built-in tools for calculations, task completion, and MCP integration
- **Prompt Building**: ReAct framework prompts and template system
- **Agent Runners**: Synchronous and asynchronous agent execution engines
- **Goal Evaluation**: Progress tracking and success criteria evaluation

## Key Features

- **Zero Dependencies** on other AgentArea libraries
- **Multi-Provider LLM Support** via LiteLLM
- **Tool System** with OpenAI function calling compatibility
- **ReAct Framework** for structured reasoning and acting
- **Streaming Support** for real-time responses
- **MCP Integration** for external tool connectivity
- **Middleware Architecture** for stateful agents (inspired by LangChain Deep Agents)

## Quick Start

### Simple Usage (Recommended)

```python
import asyncio
from agent import create_agent

async def example():
    # Create an agent - model parameter is required
    agent = create_agent(
        name="Math Assistant",
        instruction="You are a helpful math assistant.",
        model="ollama_chat/qwen2.5"  # Required: provider/model_name format
    )

    # Stream the response in real-time
    async for content in agent.run_stream("Calculate 25 * 4 + 15 and explain your work"):
        print(content, end="")

    # Or get the complete result at once
    result = await agent.run("What is 7 * 8?")
    print(result)

asyncio.run(example())
```

### Advanced Usage

```python
import asyncio
from agentic.models.llm_model import LLMModel, LLMRequest
from agentic.tools.tool_executor import ToolExecutor
from agentic.tools.calculate_tool import CalculateTool
from agentic.prompts import PromptBuilder

async def advanced_example():
    # Set up LLM model
    model = LLMModel(
        provider_type="ollama_chat",
        model_name="qwen2.5",
        endpoint_url=None
    )

    # Set up tools
    tool_executor = ToolExecutor()
    tool_executor.registry.register(CalculateTool())
    tools = tool_executor.get_openai_functions()

    # Create request with tools
    request = LLMRequest(
        messages=[
            {"role": "user", "content": "Calculate 15 * 8 + 12"}
        ],
        tools=tools,
        temperature=0.3
    )

    # Stream response
    async for chunk in model.ainvoke_stream(request):
        if chunk.content:
            print(chunk.content, end="")
        if chunk.tool_calls:
            # Execute tools
            for tool_call in chunk.tool_calls:
                result = await tool_executor.execute_tool(
                    tool_call["function"]["name"],
                    tool_call["function"]["arguments"]
                )
                print(f"Tool result: {result}")

asyncio.run(advanced_example())
```

### Stateful Agent with Middleware

```python
import asyncio
from agentarea_agents_sdk import StatefulAgent

async def stateful_example():
    agent = StatefulAgent(
        name="Research Assistant",
        instruction="You are a research assistant that plans and executes tasks methodically.",
        model_provider="ollama_chat",
        model_name="qwen2.5",
        # Default middleware enabled:
        # - TodoListMiddleware: task planning via write_todos tool
        # - FilesystemMiddleware: context eviction for large results
        # - SubAgentMiddleware: delegate tasks to subagents
        # - SummarizationMiddleware: auto-summarize long contexts
    )

    async for content in agent.run_stream("Research Python web frameworks"):
        print(content, end="")

asyncio.run(stateful_example())
```

## Testing

Run the test suite with pytest:

```bash
# Run all tests (use test.sh to handle import issues)
./test.sh

# Run specific test categories
./test.sh tests/test_agent.py -v          # Agent class tests
./test.sh tests/test_components.py -v     # Component tests
./test.sh tests/test_integration.py -v    # Integration tests

# Run with coverage
./test.sh --cov=. --cov-report=html
```

The test suite includes:

- **Unit tests**: Agent creation, tool registration, prompt building
- **Component tests**: Individual SDK components (LLM, tools, prompts)
- **Integration tests**: Complete workflows with LLM interaction
- **Error handling**: Edge cases and error conditions

Run the examples:

```bash
python example.py
```

This demonstrates:

- Streaming vs non-streaming responses
- Simple math calculations with tool usage
- Complex reasoning problems
- Custom agent configurations

## Components

### High-Level Agent (`agent.py`)

- `Agent`: Main class that simplifies agent creation and execution
- `create_agent()`: Convenience function for quick agent setup
- Automatic tool registration and prompt building
- Streaming and non-streaming execution modes

### LLM Models (`models/`)

- `LLMModel`: Unified LLM interface supporting multiple providers
- `LLMRequest`/`LLMResponse`: Request/response data structures
- Streaming support for real-time responses

### Tools (`tools/`)

- `BaseTool`: Base class for all tools
- `CalculateTool`: Mathematical calculations
- `CompletionTool`: Task completion signaling
- `MCPTool`: Model Context Protocol integration
- `ToolExecutor`: Tool orchestration and execution

### Prompts (`prompts.py`)

- `PromptBuilder`: ReAct framework prompt generation
- `MessageTemplates`: Reusable prompt templates
- Support for goal-oriented agent instructions

### Runners (`runners/`)

- `SyncAgentRunner`: Synchronous agent execution
- `BaseAgentRunner`: Abstract base for custom runners
- Goal tracking and progress evaluation

### Services (`services/`)

- `GoalProgressEvaluator`: Success criteria evaluation
- Progress tracking and completion detection

### Middleware (`middleware/`)

Middleware architecture inspired by LangChain Deep Agents for stateful agent execution:

- `Middleware`: Protocol defining lifecycle hooks (before/after LLM calls, before/after tool calls)
- `MiddlewareStack`: Manages execution of multiple middleware in sequence
- `InMemoryState`: In-memory state backend for agent execution

**Built-in Middleware:**

- `TodoListMiddleware`: Task planning and progress tracking via `write_todos` tool
- `FilesystemMiddleware`: Virtual filesystem and context eviction for large results (>80KB)
- `SummarizationMiddleware`: Auto-summarizes conversation when token limit exceeded
- `SubAgentMiddleware`: Delegates tasks to isolated subagents via `task` tool

### StatefulAgent (`agents/stateful_agent.py`)

- `StatefulAgent`: Agent with full middleware support
- Automatic middleware stack configuration
- State persistence across iterations
- Subagent delegation for complex tasks

## Architecture

The SDK follows a clean architecture with no dependencies on other AgentArea libraries:

```
agentarea-agents-sdk/
├── agentarea_agents_sdk/    # Main package
│   ├── agents/              # Agent implementations
│   │   ├── agent.py         # High-level Agent class
│   │   └── stateful_agent.py # StatefulAgent with middleware
│   ├── middleware/          # Middleware components
│   │   ├── base.py          # Middleware protocol and stack
│   │   ├── state.py         # State backends
│   │   ├── todolist.py      # TodoListMiddleware
│   │   ├── filesystem.py    # FilesystemMiddleware
│   │   ├── summarization.py # SummarizationMiddleware
│   │   └── subagents.py     # SubAgentMiddleware
│   ├── models/              # LLM interfaces
│   ├── tools/               # Tool system
│   ├── runners/             # Agent execution engines
│   └── prompts.py           # Prompt templates
├── tests/                   # Test suite
│   ├── test_agent.py
│   ├── test_middleware.py   # Middleware tests
│   └── ...
└── README.md
```

## Requirements

- Python 3.12+
- LiteLLM for LLM provider integration
- Pydantic for data validation
- httpx for HTTP requests

## License

Part of the AgentArea platform - see main repository for license details.
