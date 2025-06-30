# AgentArea System Architecture

## Overview

AgentArea is an A2A (Agent-to-Agent) protocol compliant system that provides:
- **Agent Management** with database persistence
- **LLM Integration** via Google ADK + LiteLLM  
- **Chat Interface** supporting both A2A protocol and REST APIs
- **Task Management** with event-driven architecture
- **Secret Management** with Infisical integration
- **MCP (Model Context Protocol) Server** support

## Key Architectural Principles

✅ **Proper Separation of Concerns**
- LLM services handle **configuration/data management**
- Agent runner handles **execution** via Google ADK
- Chat services handle **protocol translation**
- Secret managers handle **secure storage**

✅ **Event-Driven Architecture**
- Redis-backed event broker for real-time communication
- Task lifecycle events (submitted → working → completed/failed)
- Agent communication events

✅ **Protocol Compliance**
- A2A protocol support (JSON-RPC + REST)
- Google A2A specification compliance
- Backward compatibility with existing APIs

## Core Components

### 1. LLM Management Layer

**Purpose**: Configuration and metadata management (NOT execution)

```
agentarea/modules/llm/
├── application/
│   ├── llm_model_service.py       # Model metadata management
│   └── service.py                 # Instance management + secrets
├── domain/
│   ├── models.py                  # LLMProvider, LLMModel, LLMModelInstance
│   └── events.py                  # LLM-related events
└── infrastructure/
    ├── llm_model_repository.py    # Database persistence
    └── llm_model_instance_repository.py
```

**Key Insight**: These services DON'T execute LLMs - they manage configuration that gets used by the agent runner.

### 2. Agent Execution Layer

**Purpose**: Actual LLM execution via Google ADK

```
agentarea/modules/agents/application/agent_runner_service.py
```

**Key Integration Point**:
```python
# Get model instance from database
model_instance = agent_config["model_instance"]

# Convert to LiteLLM format for Google ADK
litellm_model_string = self._create_litellm_model_from_instance(model_instance)

# Execute via Google ADK (NOT custom code)
litellm_model = LiteLlm(model=litellm_model_string)
llm_agent = LlmAgent(name=name, model=litellm_model, ...)
```

**Supported Formats**:
- `ollama_chat/qwen2.5` for Ollama
- `openai/gpt-3.5-turbo` for OpenAI
- Extensible for other LiteLLM providers

### 3. Protocol Layer

**Purpose**: A2A protocol compliance + REST API compatibility

```
agentarea/api/v1/
├── protocol.py                    # Unified A2A + REST protocol
├── chat.py                        # Consolidated chat interface
├── agents.py                      # Agent management
├── llm_model_instances.py         # LLM configuration APIs
└── tasks.py                       # Task management
```

**Protocol Support**:
- **JSON-RPC Methods**: `message/send`, `message/stream`, `tasks/get`, `agent/authenticatedExtendedCard`
- **REST Endpoints**: `/messages`, `/tasks/{id}`, `/agents/{id}/card`, `/health`
- **WebSocket**: Real-time streaming support

### 4. Infrastructure Layer

**Purpose**: Foundation services

```
agentarea/common/infrastructure/
├── database.py                    # PostgreSQL async sessions
├── secret_manager.py              # Infisical + local fallback
├── infisical_factory.py           # Production secret management
└── local_secret_manager.py        # Development secret management
```

**Secret Management**:
- **Production**: Infisical integration for secure secret storage
- **Development**: Local `.secrets.json` file
- **Pattern**: `llm_model_instance_{instance_id}` for API keys

## Data Flow

### 1. Agent Task Execution
```
[Client Request] 
    → [Chat API] 
    → [Agent Service] 
    → [Agent Runner Service]
    → [Google ADK + LiteLLM]
    → [LLM Provider (Ollama/OpenAI/etc)]
    → [Streaming Response]
    → [Client]
```

### 2. LLM Configuration Flow
```
[Admin creates LLM Model] 
    → [LLMModelService] 
    → [Database]

[Admin creates Instance with API key] 
    → [LLMModelInstanceService] 
    → [Secret Manager] 
    → [Database]

[Agent execution needs LLM] 
    → [Agent Runner Service] 
    → [LLMModelInstanceService] 
    → [Convert to LiteLLM format] 
    → [Google ADK]
```

### 3. Event Flow
```
[Task Created] 
    → [Event Broker] 
    → [Redis] 
    → [Task Service] 
    → [Status Updates]

[Agent Communication] 
    → [A2A Adapter] 
    → [Event Broker] 
    → [Target Agent]
```

## Service Dependencies

### Dependency Injection Pattern
```python
# services.py - Proper composition
async def get_agent_service(
    event_broker: EventBroker,
    agent_repository: AgentRepository
) -> AgentService:
    return AgentService(repository=agent_repository, event_broker=event_broker)
```

### Database Session Management
```python
# Request-scoped sessions for transaction isolation
async def get_task_repository(db: AsyncSession):
    return TaskRepository(db)
```

## Integration Points

### 1. LLM Provider Integration
**Current**: Ollama via `ollama_chat/qwen2.5`
**Future**: OpenAI, Anthropic, etc. via LiteLLM format strings

### 2. Agent-to-Agent Communication
**Protocol**: A2A specification compliance
**Transport**: HTTP/WebSocket for real-time communication
**Security**: API key authentication via secret manager

### 3. MCP Server Integration
**Purpose**: Tool/function calling for agents
**Status**: Infrastructure ready, implementation in progress

## Configuration Management

### Environment-Based Configuration
```python
# config.py
class Settings:
    database_url: str
    redis_url: str
    infisical_project_id: Optional[str]
    broker: str = "redis"  # or "memory"
```

### Secret Storage
```json
// .secrets.json (development)
{
    "llm_model_instance_{uuid}": "api_key_here",
    "infisical_token": "optional_production_token"
}
```

## What We Learned

### ❌ **Over-Engineering Mistakes**
1. **Custom LLM Providers**: Not needed - Google ADK handles this
2. **Strategy/Factory Patterns**: Over-engineered for this use case
3. **Custom Execution Services**: Duplicated Google ADK functionality

### ✅ **Proper Architecture**
1. **Data Management Services**: LLM services handle configuration only
2. **Execution Delegation**: Google ADK + LiteLLM handle actual execution
3. **Clean Integration**: Database instances → LiteLLM format → Google ADK
4. **Protocol Compliance**: A2A + REST support without duplication

## Development Patterns

### Adding New LLM Providers
1. **Database**: Create LLMProvider entry
2. **Instance**: Create LLMModelInstance with provider reference
3. **Runner**: Update `_create_litellm_model_from_instance()` mapping
4. **No custom provider code needed** - LiteLLM handles it

### Adding New Agent Features
1. **Domain**: Add to agent models
2. **Service**: Extend AgentService methods
3. **API**: Add endpoints in agents.py
4. **Integration**: Update agent_runner_service.py if needed

### Adding New Protocols
1. **Protocol**: Extend protocol.py with new methods
2. **Chat**: Add translation layer in chat.py
3. **Events**: Add event types if needed
4. **Docs**: Update API documentation

This architecture provides a clean separation between configuration management and execution, leveraging existing tools (Google ADK, LiteLLM) for the heavy lifting while maintaining full control over the business logic and protocol compliance. 