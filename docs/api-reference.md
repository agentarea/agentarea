# AgentArea API Reference

## 🔗 Base Information

- **Base URL**: `http://localhost:8000` (development)
- **API Version**: v1
- **Content Type**: `application/json`
- **Authentication**: Bearer token (see [Auth Implementation](auth_implementation.md))

## 📚 Interactive Documentation

**Live API Documentation**: `http://localhost:8000/docs`

The interactive Swagger/OpenAPI documentation provides:
- Real-time API testing
- Request/response examples
- Schema definitions
- Authentication testing

## 🚀 Quick Start

### Health Check
```bash
curl -X GET http://localhost:8000/health
```

**Response:**
```json
{
  "status": "healthy",
  "timestamp": "2025-01-XX T XX:XX:XX.XXXZ",
  "version": "1.0.0"
}
```

### Authentication
```bash
# Get access token
curl -X POST http://localhost:8000/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{
    "username": "your-username",
    "password": "your-password"
  }'

# Use token in subsequent requests
curl -X GET http://localhost:8000/v1/agents/ \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN"
```

## 🤖 Agents API

### List Agents
```http
GET /v1/agents/
```

**Parameters:**
- `limit` (query, optional): Number of results (default: 20, max: 100)
- `offset` (query, optional): Pagination offset (default: 0)
- `type` (query, optional): Filter by agent type
- `status` (query, optional): Filter by status (`active`, `inactive`, `error`)

**Response:**
```json
{
  "agents": [
    {
      "id": "agent-123",
      "name": "chat-assistant",
      "description": "General purpose chat agent",
      "type": "chat",
      "status": "active",
      "created_at": "2025-01-XX T XX:XX:XX.XXXZ",
      "updated_at": "2025-01-XX T XX:XX:XX.XXXZ",
      "created_by": "user-456",
      "config": {
        "model": "gpt-4",
        "temperature": 0.7
      }
    }
  ],
  "total": 1,
  "limit": 20,
  "offset": 0
}
```

### Create Agent
```http
POST /v1/agents/
```

**Request Body:**
```json
{
  "name": "my-agent",
  "description": "Agent description",
  "type": "chat",
  "config": {
    "model": "gpt-4",
    "temperature": 0.7,
    "max_tokens": 2000
  }
}
```

**Response:**
```json
{
  "id": "agent-789",
  "name": "my-agent",
  "description": "Agent description",
  "type": "chat",
  "status": "active",
  "created_at": "2025-01-XX T XX:XX:XX.XXXZ",
  "updated_at": "2025-01-XX T XX:XX:XX.XXXZ",
  "created_by": "user-456",
  "config": {
    "model": "gpt-4",
    "temperature": 0.7,
    "max_tokens": 2000
  }
}
```

### Get Agent
```http
GET /v1/agents/{agent_id}
```

### Update Agent
```http
PUT /v1/agents/{agent_id}
```

### Delete Agent
```http
DELETE /v1/agents/{agent_id}
```

## 💬 Chat API

### Send Message
```http
POST /v1/agents/{agent_id}/chat
```

**Request Body:**
```json
{
  "message": "Hello, how can you help me?",
  "session_id": "session-123",
  "stream": false
}
```

**Response (Non-streaming):**
```json
{
  "id": "msg-456",
  "message": "Hello! I'm here to help you with...",
  "session_id": "session-123",
  "timestamp": "2025-01-XX T XX:XX:XX.XXXZ",
  "metadata": {
    "model": "gpt-4",
    "tokens_used": 150
  }
}
```

### Streaming Chat
```http
POST /v1/agents/{agent_id}/chat
Content-Type: application/json

{
  "message": "Tell me a story",
  "session_id": "session-123",
  "stream": true
}
```

**Response (Server-Sent Events):**
```
data: {"type": "start", "session_id": "session-123"}

data: {"type": "token", "content": "Once"}

data: {"type": "token", "content": " upon"}

data: {"type": "token", "content": " a"}

data: {"type": "end", "message_id": "msg-789", "metadata": {"tokens_used": 245}}
```

### Get Chat History
```http
GET /v1/agents/{agent_id}/chat/history
```

**Parameters:**
- `session_id` (query, optional): Filter by session
- `limit` (query, optional): Number of messages (default: 50)
- `before` (query, optional): Messages before timestamp

## 🔌 MCP Servers API

### List MCP Servers
```http
GET /v1/mcp-servers/
```

**Response:**
```json
{
  "servers": [
    {
      "id": "server-123",
      "name": "file-operations",
      "slug": "file-ops",
      "status": "running",
      "url": "http://localhost:81/mcp/file-ops/mcp/",
      "capabilities": ["tools", "resources"],
      "created_at": "2025-01-XX T XX:XX:XX.XXXZ"
    }
  ]
}
```

### Create MCP Server
```http
POST /v1/mcp-servers/
```

**Request Body:**
```json
{
  "name": "my-mcp-server",
  "slug": "my-server",
  "config": {
    "command": "python",
    "args": ["-m", "my_mcp_server"],
    "env": {
      "API_KEY": "secret-key"
    }
  }
}
```

### Get MCP Server
```http
GET /v1/mcp-servers/{server_id}
```

### Update MCP Server
```http
PUT /v1/mcp-servers/{server_id}
```

### Delete MCP Server
```http
DELETE /v1/mcp-servers/{server_id}
```

### MCP Server Actions
```http
# Start server
POST /v1/mcp-servers/{server_id}/start

# Stop server
POST /v1/mcp-servers/{server_id}/stop

# Restart server
POST /v1/mcp-servers/{server_id}/restart

# Get server logs
GET /v1/mcp-servers/{server_id}/logs
```

## 🔐 Authentication API

### Login
```http
POST /v1/auth/login
```

**Request Body:**
```json
{
  "username": "your-username",
  "password": "your-password"
}
```

**Response:**
```json
{
  "access_token": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "user": {
    "id": "user-123",
    "username": "your-username",
    "email": "developer@localhost"
  }
}
```

### Refresh Token
```http
POST /v1/auth/refresh
```

### Logout
```http
POST /v1/auth/logout
```

### Get Current User
```http
GET /v1/auth/me
```

## 📊 Tasks API

### Create Task
```http
POST /v1/tasks/
```

**Request Body:**
```json
{
  "title": "Process document",
  "description": "Extract key information from uploaded document",
  "agent_id": "agent-123",
  "priority": "high",
  "data": {
    "document_url": "http://localhost:8000/uploads/doc.pdf",
    "extract_fields": ["name", "date", "amount"]
  }
}
```

### List Tasks
```http
GET /v1/tasks/
```

**Parameters:**
- `status` (query, optional): Filter by status (`pending`, `running`, `completed`, `failed`)
- `agent_id` (query, optional): Filter by agent
- `priority` (query, optional): Filter by priority (`low`, `medium`, `high`)

### Get Task
```http
GET /v1/tasks/{task_id}
```

### Cancel Task
```http
POST /v1/tasks/{task_id}/cancel
```

## 📁 Files API

### Upload File
```http
POST /v1/files/upload
Content-Type: multipart/form-data

file: [binary data]
metadata: {"description": "Document for processing"}
```

### List Files
```http
GET /v1/files/
```

### Get File
```http
GET /v1/files/{file_id}
```

### Download File
```http
GET /v1/files/{file_id}/download
```

### Delete File
```http
DELETE /v1/files/{file_id}
```

## 📡 WebSocket API

### Connection
```javascript
// Connect to WebSocket
const ws = new WebSocket('ws://localhost:8000/v1/ws');

// Authentication
ws.send(JSON.stringify({
  type: 'auth',
  token: 'your-access-token'
}));

// Subscribe to agent events
ws.send(JSON.stringify({
  type: 'subscribe',
  channel: 'agent.agent-123.events'
}));
```

### Message Types
```javascript
// Task status updates
{
  "type": "task.status",
  "task_id": "task-123",
  "status": "completed",
  "result": {...}
}

// Agent events
{
  "type": "agent.message",
  "agent_id": "agent-123",
  "session_id": "session-456",
  "message": "Processing your request..."
}

// System notifications
{
  "type": "system.notification",
  "level": "info",
  "message": "MCP server restarted"
}
```

## 🚨 Error Handling

### Error Response Format
```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "Invalid request data",
    "details": {
      "field": "name",
      "issue": "Field is required"
    },
    "request_id": "req-123"
  }
}
```

### Common Error Codes

| Code | Status | Description |
|------|--------|--------------|
| `VALIDATION_ERROR` | 400 | Invalid request data |
| `UNAUTHORIZED` | 401 | Authentication required |
| `FORBIDDEN` | 403 | Insufficient permissions |
| `NOT_FOUND` | 404 | Resource not found |
| `CONFLICT` | 409 | Resource already exists |
| `RATE_LIMITED` | 429 | Too many requests |
| `INTERNAL_ERROR` | 500 | Server error |
| `SERVICE_UNAVAILABLE` | 503 | Service temporarily unavailable |

## 📊 Rate Limiting

- **Default Limit**: 100 requests per minute per user
- **Burst Limit**: 20 requests per second
- **Headers**: `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`

## 🔧 SDK Examples

### Python
```python
import requests

# Initialize client
class AgentAreaClient:
    def __init__(self, base_url, token):
        self.base_url = base_url
        self.headers = {'Authorization': f'Bearer {token}'}
    
    def create_agent(self, name, agent_type, config):
        response = requests.post(
            f'{self.base_url}/v1/agents/',
            json={'name': name, 'type': agent_type, 'config': config},
            headers=self.headers
        )
        return response.json()

# Usage
client = AgentAreaClient('http://localhost:8000', 'your-token')
agent = client.create_agent('test-agent', 'chat', {'model': 'gpt-4'})
```

### JavaScript
```javascript
class AgentAreaClient {
  constructor(baseUrl, token) {
    this.baseUrl = baseUrl;
    this.headers = {
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json'
    };
  }

  async createAgent(name, type, config) {
    const response = await fetch(`${this.baseUrl}/v1/agents/`, {
      method: 'POST',
      headers: this.headers,
      body: JSON.stringify({ name, type, config })
    });
    return response.json();
  }
}

// Usage
const client = new AgentAreaClient('http://localhost:8000', 'your-token');
const agent = await client.createAgent('test-agent', 'chat', { model: 'gpt-4' });
```

## 📚 Additional Resources

- **[Interactive API Docs](http://localhost:8000/docs)** - Live testing interface
- **[Authentication Guide](auth_implementation.md)** - Detailed auth implementation
- **[A2A Integration](../core/docs/A2A_INTEGRATION_GUIDE.md)** - Agent communication
- **[MCP Architecture](mcp_architecture.md)** - MCP system design
- **[Getting Started](getting-started.md)** - Setup and first steps

---

*API Reference last updated: January 2025*
*For the most current API documentation, always refer to the interactive docs at `/docs`*