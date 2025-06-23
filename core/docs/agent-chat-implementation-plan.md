# Agent Task Implementation Plan

## Overview
Implement comprehensive agent communication using a **task-centric hybrid architecture** that provides clean APIs compatible with CopilotKit/Assistants-UI while supporting multiple agent protocols through adapters. **All interactions with agents are treated as tasks** - whether they're chat messages or complex operations.

## 🎯 **Key Architectural Insights**

### ✅ **Task-Centric Approach**
- **Everything is a Task**: Chat messages, actions, queries - all are tasks from agent perspective
- **Unified Interface**: No distinction between "chat" and "task" from user perspective  
- **Agent Perspective**: When you send something to an agent, it's always a task to execute
- **Flexible Task Types**: `message`, `action`, `query`, `analysis`, etc.

### ✅ **Remote Agent Reality**
- **A2A Agents**: External services we don't host (OpenAI, Anthropic, etc.)
- **ACP Agents**: BeeAI ecosystem agents running elsewhere
- **Native Agents**: Only our internal agents
- **Agent Creation**: Support creating new agents on remote platforms

### ✅ **Dual Interface Strategy**
- **Frontend**: Clean `/chat/*` endpoints for UI compatibility
- **Backend**: Task-centric `/tasks/*` endpoints for explicit task operations
- **Backward Compatible**: Chat endpoints map to task operations internally

## 1. Protocol Adapter System ✅

### Base Adapter Interface
**Location**: `core/agentarea/modules/agents/adapters/base.py`

**Key Components**:
- `AgentTask`: Standard internal task format with `task_type`, `context`, `metadata`
- `AgentTaskResponse`: Standard response with `artifacts`, `status`, `metadata`
- `AgentAdapter`: Abstract base class for all adapters

**Methods**:
- `send_task()`: Send task and get response
- `stream_task()`: Stream task response chunks
- `get_capabilities()`: Get agent capabilities
- `health_check()`: Check agent availability
- `create_agent()`: Create new agent instance (for remote platforms)

### A2A Protocol Adapter ✅
**Location**: `core/agentarea/modules/agents/adapters/a2a_adapter.py`

**Features**:
- **Remote Agent Communication**: HTTP calls to external A2A services
- **Task Translation**: Maps `AgentTask` to A2A Task format
- **Authentication**: Supports API keys for remote services
- **Agent Creation**: Can create new agents on A2A platforms
- **Polling Support**: Handles async task completion
- **Artifact Extraction**: Gets responses from task artifacts

**Example Remote A2A Agent**:
```python
# Register external OpenAI A2A agent
task_service.register_agent("openai-gpt4", {
    "id": "openai-gpt4",
    "name": "OpenAI GPT-4",
    "protocol": "a2a", 
    "endpoint": "https://api.openai.com/v1/a2a",
    "api_key": "sk-...",
    "timeout": 30
})
```

### ACP Protocol Adapter ✅  
**Location**: `core/agentarea/modules/agents/adapters/acp_adapter.py`

**Features**:
- **BeeAI Ecosystem**: Compatible with BeeAI platform agents
- **Remote Communication**: HTTP calls to ACP endpoints
- **Context Handling**: Maps task context to ACP format
- **Agent Creation**: Can create agents on BeeAI platforms

### Native Adapter ✅
**Location**: `core/agentarea/modules/agents/adapters/native_adapter.py`

**Features**:
- **Internal Agents**: Direct communication with local agents
- **No Protocol Translation**: Direct method calls
- **Instance Management**: Holds reference to agent instance

## 2. Unified Task Service ✅

### Core Service
**Location**: `core/agentarea/modules/chat/unified_chat_service.py`

**Key Features**:
- **Task-Centric**: All operations are task-based
- **Protocol Agnostic**: Uses adapters for different protocols
- **Session Management**: Groups related tasks by `session_id`
- **Agent Registry**: Dynamic agent registration and creation
- **Remote Agent Support**: Handles external agent communication

**Methods**:
- `register_agent()`: Register existing agent with adapter
- `create_agent()`: Create new agent on remote platform
- `send_task()`: Send task via appropriate adapter
- `stream_task()`: Stream task response via adapter  
- `get_session_history()`: Get task history for session
- `list_sessions()`: List all task sessions
- `get_available_agents()`: List registered agents
- `get_platforms()`: List platforms that support agent creation

## 3. Clean API Endpoints ✅

### Dual Interface Design
**Location**: `core/agentarea/api/v1/chat.py`

#### Chat-Compatible Endpoints (UI Friendly)
```http
POST   /chat/messages                              # Send message/task
POST   /chat/messages/stream                       # Stream response
GET    /chat/conversations/{id}/messages           # Get session history
GET    /chat/conversations                         # List sessions
GET    /chat/agents                                # List agents
POST   /chat/agents/{id}/register                  # Register existing agent
POST   /chat/agents/create                         # Create new agent
GET    /chat/platforms                             # List creation platforms
```

#### Explicit Task Endpoints
```http
POST   /tasks                                      # Send task explicitly
POST   /tasks/stream                               # Stream task response
```

**Features**:
- **Backward Compatible**: Chat endpoints work with existing UIs
- **Task-Centric**: All operations map to task operations internally
- **Agent Creation**: Support creating agents on remote platforms
- **Platform Discovery**: List available platforms for agent creation

## 4. Usage Examples

### Register Remote A2A Agent
```python
# Register external A2A service as platform
await task_service.register_agent("openai-platform", {
    "id": "openai-platform",
    "name": "OpenAI Platform", 
    "protocol": "a2a",
    "endpoint": "https://api.openai.com/v1/a2a",
    "api_key": "sk-...",
    "timeout": 30
})
```

### Create Agent on Remote Platform
```python
# Create new GPT-4 agent on OpenAI platform
agent_info = await task_service.create_agent("openai-platform", {
    "name": "My Custom GPT-4",
    "description": "Specialized assistant for code review",
    "model": "gpt-4",
    "instructions": "You are a code review expert...",
    "capabilities": ["code-analysis", "documentation"]
})
# Returns: {"id": "agent-123", "name": "My Custom GPT-4", "endpoint": "..."}
```

### Send Task to Any Agent
```python
# Send task to remote agent (same interface for all)
response = await task_service.send_task(
    content="Review this Python code for security issues",
    agent_id="agent-123",  # Created above
    task_type="code-review",
    session_id="session-456",
    context={"code": "def login(user, pass): ..."},
    user_id="user-789"
)
```

### Different Task Types
```python
# Chat message
await task_service.send_task(
    content="Hello, how are you?",
    agent_id="agent-123",
    task_type="message"  # Default
)

# Code analysis
await task_service.send_task(
    content="Analyze this code for bugs",
    agent_id="agent-123", 
    task_type="analysis",
    context={"code": "...", "language": "python"}
)

# Action request
await task_service.send_task(
    content="Create a new file with this content",
    agent_id="agent-123",
    task_type="action",
    context={"filename": "test.py", "content": "..."}
)
```

## 5. Frontend Integration

### CopilotKit Integration
```typescript
// Works seamlessly with existing chat endpoints
const copilotConfig = {
  chatApiEndpoint: "/api/v1/chat/messages",
  streamingEndpoint: "/api/v1/chat/messages/stream"
}

// Can also use explicit task endpoints
const taskConfig = {
  taskApiEndpoint: "/api/v1/tasks",
  streamingEndpoint: "/api/v1/tasks/stream"
}
```

### Agent Creation UI
```typescript
// Get available platforms
const platforms = await fetch('/api/v1/chat/platforms').then(r => r.json())

// Create agent on selected platform
const newAgent = await fetch('/api/v1/chat/agents/create', {
  method: 'POST',
  body: JSON.stringify({
    platform_id: 'openai-platform',
    name: 'My Assistant',
    model: 'gpt-4',
    instructions: 'You are a helpful assistant...'
  })
})
```

## 6. Benefits of Task-Centric Architecture

### 🎯 **Conceptual Clarity**
- **Agent Perspective**: Everything sent to an agent is a task
- **Unified Model**: No artificial distinction between chat/tasks
- **Natural Mapping**: UI "messages" are just `task_type: "message"`
- **Extensible**: Easy to add new task types

### 🎯 **Remote Agent Support**
- **Platform Agnostic**: Works with any remote agent service
- **Agent Creation**: Can create agents on external platforms
- **Authentication**: Supports API keys and auth tokens
- **Discovery**: Can list available platforms and capabilities

### 🎯 **UI Compatibility**
- **Backward Compatible**: Existing chat UIs work unchanged
- **Progressive Enhancement**: Can expose task features gradually
- **Framework Agnostic**: Works with CopilotKit, Assistants-UI, custom UIs

### 🎯 **Operational Flexibility**
- **Task Types**: Support different operation types
- **Context Passing**: Rich context for complex tasks
- **Artifact Handling**: Support file attachments, code, etc.
- **Session Grouping**: Related tasks grouped by session

## 7. Real-World Scenarios

### Scenario 1: Chat with Remote GPT-4
```python
# 1. Register OpenAI as A2A platform
# 2. Create custom GPT-4 agent
# 3. Chat normally through /chat/messages
# 4. All messages become tasks sent to remote OpenAI A2A endpoint
```

### Scenario 2: Code Review Task
```python
# 1. Send code review task with context
# 2. Agent analyzes code and returns artifacts
# 3. UI displays both text response and code annotations
```

### Scenario 3: Multi-Agent Session
```python
# 1. Start session with planning agent
# 2. Switch to coding agent in same session  
# 3. Switch to review agent for final check
# 4. All tasks grouped by session_id
```

This task-centric approach perfectly aligns with your insight that **"for an agent, when we send something - it's a task"** while maintaining clean APIs that work with existing chat frameworks. 