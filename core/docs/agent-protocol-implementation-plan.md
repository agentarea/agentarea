# Agent Protocol Implementation Plan

## Overview

This plan consolidates the duplicate task/chat implementations into a single, A2A protocol-compliant system that supports both JSON-RPC and REST interfaces while maintaining compatibility with frontend frameworks like CopilotKit.

## Current State Analysis

### Duplicate Implementations
1. **`/api/v1/a2a_chat.py`** - A2A-native chat endpoints
2. **`/api/v1/chat.py`** - Clean task API endpoints 
3. **`/api/v1/tasks.py`** - Mixed A2A JSON-RPC and REST endpoints

### Issues Identified
- Code duplication across multiple files
- Inconsistent API patterns
- Abstract methods not implemented in `InMemoryTaskManager`
- Mixed naming conventions (explicit "a2a" references)
- Incomplete A2A protocol implementation

## Implementation Plan

### Phase 1: Core Protocol Implementation

#### 1.1 Complete A2A Protocol Types
**File**: `agentarea/common/utils/types.py`

Add missing A2A protocol types:
- `AgentCard` and related objects
- `AuthenticatedExtendedCardParams`
- `PushNotificationAuthenticationInfo`
- File handling types (`FileWithBytes`, `FileWithUri`)
- Streaming event types

#### 1.2 Fix InMemoryTaskManager
**File**: `agentarea/modules/tasks/in_memory_task_manager.py`

Implement missing abstract methods:
- `on_send_task()` - Core task sending logic
- `on_send_task_subscribe()` - SSE streaming implementation

#### 1.3 Create Unified Protocol Service
**File**: `agentarea/modules/protocol/service.py` (new)

Single service that handles:
- A2A JSON-RPC protocol
- Agent discovery via Agent Cards
- Message/task routing
- Authentication/authorization
- Push notifications

### Phase 2: API Consolidation

#### 2.1 Remove Duplicate Files
Delete:
- `agentarea/api/v1/a2a_chat.py`
- `agentarea/api/v1/chat.py`

#### 2.2 Create Unified Endpoints
**File**: `agentarea/api/v1/protocol.py` (new)

Implement A2A specification endpoints:

**JSON-RPC Methods:**
- `POST /protocol/rpc` - Single JSON-RPC endpoint
  - `message/send`
  - `message/stream`
  - `tasks/get`
  - `tasks/cancel`
  - `tasks/pushNotificationConfig/set`
  - `tasks/pushNotificationConfig/get`
  - `tasks/resubscribe`
  - `agent/authenticatedExtendedCard`

**REST Methods (for compatibility):**
- `GET /protocol/agents/{agent_id}/card` - Agent discovery
- `POST /protocol/messages` - Send message
- `GET /protocol/messages/stream` - SSE streaming
- `GET /protocol/tasks/{task_id}` - Get task
- `DELETE /protocol/tasks/{task_id}` - Cancel task

#### 2.3 Update Main Router
**File**: `agentarea/api/v1/router.py`

Replace chat/task routers with unified protocol router.

### Phase 3: Agent Discovery

#### 3.1 Agent Card Service
**File**: `agentarea/modules/agents/card_service.py` (new)

Implement agent discovery:
- Agent card generation
- Capability advertisement
- Security scheme definition
- Extended card authentication

#### 3.2 Agent Card Storage
**File**: `agentarea/modules/agents/infrastructure/card_repository.py` (new)

Store and retrieve agent cards:
- Database persistence
- Card validation
- Version management

### Phase 4: Protocol Features

#### 4.1 Authentication System
**File**: `agentarea/modules/protocol/auth.py` (new)

Implement A2A authentication:
- Bearer token validation
- API key support
- Server identity verification
- In-task authentication

#### 4.2 Streaming Implementation
**File**: `agentarea/modules/protocol/streaming.py` (new)

Server-Sent Events (SSE) support:
- Task status updates
- Artifact updates
- Connection management
- Error handling

#### 4.3 Push Notifications
**File**: `agentarea/modules/protocol/notifications.py` (new)

Webhook-based notifications:
- Configuration management
- Webhook validation
- Authentication
- Delivery tracking

### Phase 5: Testing and Integration

#### 5.1 Setup Test Environment
**File**: `tests/integration/test_protocol.py` (new)

End-to-end testing:
- A2A protocol compliance
- Multi-agent communication
- Streaming functionality
- Authentication flows

#### 5.2 Ollama Integration
**File**: `agentarea/modules/llm/ollama_service.py` (new)

LLM server setup:
- Ollama integration
- qwen2.5:latest model
- A2A protocol adapter
- Testing endpoints

#### 5.3 Frontend Compatibility
**File**: `tests/integration/test_frontend_compat.py` (new)

Ensure compatibility with:
- CopilotKit
- Assistants-UI
- Custom frontends

## Directory Structure

```
agentarea/
├── api/v1/
│   ├── protocol.py          # Unified A2A endpoints
│   ├── tasks.py            # Updated task management
│   └── router.py           # Updated main router
├── modules/
│   ├── protocol/           # New protocol module
│   │   ├── service.py      # Core protocol service
│   │   ├── auth.py         # Authentication
│   │   ├── streaming.py    # SSE streaming
│   │   └── notifications.py # Push notifications
│   ├── agents/
│   │   ├── card_service.py # Agent discovery
│   │   └── infrastructure/
│   │       └── card_repository.py # Card storage
│   ├── llm/
│   │   └── ollama_service.py # Ollama integration
│   └── tasks/
│       └── in_memory_task_manager.py # Fixed implementation
└── common/utils/
    └── types.py            # Complete A2A types
```

## Implementation Order

1. **Phase 1** (Core): Fix types and base implementations
2. **Phase 2** (APIs): Consolidate endpoints
3. **Phase 3** (Discovery): Agent cards and discovery
4. **Phase 4** (Features): Authentication, streaming, notifications
5. **Phase 5** (Testing): Integration and compatibility testing

## Success Criteria

- [ ] Single, unified API that supports A2A protocol
- [ ] No duplicate implementations
- [ ] Full A2A JSON-RPC compliance
- [ ] Agent discovery working
- [ ] SSE streaming functional
- [ ] Authentication implemented
- [ ] Ollama integration complete
- [ ] Frontend compatibility maintained
- [ ] Comprehensive test coverage

## Migration Guide

### For Frontend Developers
- Update endpoint URLs from `/chat/*` to `/protocol/*`
- Use A2A message format for advanced features
- Leverage SSE streaming for real-time updates

### For Agent Developers
- Implement A2A agent cards for discovery
- Use A2A protocol for agent-to-agent communication
- Support authentication schemes defined in cards

### For Backend Developers
- Use unified `ProtocolService` for all agent communication
- Implement agents using A2A adapters
- Follow A2A patterns for new features

## Next Steps

1. Start with Phase 1 implementation
2. Set up comprehensive testing
3. Implement in order of dependencies
4. Test each phase before proceeding
5. Maintain backward compatibility during transition 