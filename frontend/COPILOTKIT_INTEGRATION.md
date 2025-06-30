# CopilotKit Integration with AgentArea

This document explains how AgentArea integrates CopilotKit with the A2A protocol via AG-UI.

## Architecture Overview

```
Frontend (CopilotKit) → AG-UI Protocol → A2A Backend → AgentArea Agents
```

## Components

### 1. Backend Integration (`/v1/protocol/ag-ui`)

The backend provides an AG-UI endpoint that:
- Accepts AG-UI formatted requests from CopilotKit
- Converts them to A2A protocol messages
- Streams responses back as AG-UI events

**Key Features:**
- Real-time streaming via Server-Sent Events (SSE)
- Event-driven architecture with lifecycle, text-delta, and state events
- Seamless integration with existing A2A infrastructure

### 2. Frontend Integration

The frontend uses CopilotKit components with:
- `CopilotKit` provider wrapping the app
- `CopilotChat` component for the chat interface
- Custom actions for agent task execution

## Setup Instructions

### Backend Setup

1. The AG-UI endpoint is already integrated in `core/apps/api/agentarea_api/api/v1/protocol.py`
2. Start your backend server:
   ```bash
   cd core
   uv run uvicorn agentarea_api.main:app --reload --port 8000
   ```

### Frontend Setup

1. Install CopilotKit dependencies:
   ```bash
   cd frontend
   npm install
   ```

2. Start the frontend:
   ```bash
   npm run dev
   ```

3. Visit `http://localhost:3000/chat` to use the chat interface

## How It Works

### Request Flow

1. **User Input**: User types a message in CopilotChat
2. **AG-UI Request**: CopilotKit sends an AG-UI formatted request to `/api/copilotkit`
3. **Protocol Translation**: The frontend API route forwards to `/v1/protocol/ag-ui`
4. **A2A Processing**: Backend converts AG-UI to A2A and processes with agents
5. **Streaming Response**: AG-UI events stream back to update the UI in real-time

### Event Types

- **Lifecycle Events**: `started`, `completed`, `failed`
- **Text Delta Events**: Streaming text content
- **State Update Events**: UI state synchronization
- **Tool Call Events**: Agent tool usage (future enhancement)

## Benefits

1. **Preserve A2A Investment**: Keeps your existing A2A protocol implementation
2. **Modern Frontend**: Leverages CopilotKit's polished UI components
3. **Protocol Interoperability**: Bridges A2A (agent-to-agent) with AG-UI (agent-to-user)
4. **Real-time Experience**: Streaming responses for better user experience

## Extending the Integration

### Adding Custom Actions

```typescript
useCopilotAction({
  name: "custom_agent_action",
  description: "Custom action for specific agent workflows",
  parameters: [
    {
      name: "parameter_name",
      type: "string",
      description: "Parameter description",
      required: true,
    }
  ],
  handler: async ({ parameter_name }) => {
    // Custom logic here
    return "Action completed";
  },
});
```

### Adding Tool Support

The AG-UI endpoint can be extended to support tool calls by:
1. Detecting tool usage in A2A responses
2. Emitting `ToolCallEvent` and `ToolResultEvent` 
3. Handling tool approval flows in the frontend

## Troubleshooting

### Common Issues

1. **CORS Errors**: Ensure backend allows requests from frontend origin
2. **Streaming Issues**: Check that SSE headers are properly set
3. **Agent Not Responding**: Verify A2A backend is running and agents are configured

### Debug Mode

Enable debug mode in development:
```typescript
<CopilotKit 
  showDevConsole={true}
  // ... other props
>
```

## Future Enhancements

1. **Multi-Agent Support**: Route requests to specific agents
2. **Tool Integration**: Support for MCP server tools via AG-UI
3. **State Persistence**: Maintain conversation state across sessions
4. **Human-in-the-Loop**: Interactive approval workflows 