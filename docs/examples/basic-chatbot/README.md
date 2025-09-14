# Basic Chatbot Example

This example demonstrates how to create a simple chatbot agent using AgentArea.

## Overview

This chatbot can:
- Answer general questions
- Maintain conversation context
- Provide helpful responses
- Escalate to human agents when needed

## Quick Start

### 1. Create the Agent

```bash
curl -X POST http://localhost:8000/v1/agents \
  -H "Content-Type: application/json" \
  -d @agent-config.json
```

### 2. Start a Conversation

```bash
curl -X POST http://localhost:8000/v1/conversations \
  -H "Content-Type: application/json" \
  -d '{
    "agent_id": "your-agent-id",
    "message": "Hello! Can you help me?"
  }'
```

### 3. Continue the Conversation

```bash
curl -X POST http://localhost:8000/v1/conversations/your-conversation-id/messages \
  -H "Content-Type: application/json" \
  -d '{
    "message": "What can you do for me?"
  }'
```

## Files

- `agent-config.json` - Agent configuration
- `conversation-flow.py` - Python script example
- `web-integration.html` - Web integration example
- `test-scenarios.json` - Test cases

## Configuration

The agent configuration includes:
- Basic personality settings
- Response templates
- Escalation rules
- Context management settings

## Testing

Run the test scenarios:

```bash
python test_chatbot.py
```

This will test:
- Basic Q&A functionality
- Context retention
- Error handling
- Escalation triggers