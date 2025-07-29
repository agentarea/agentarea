# AgentArea Enhanced CLI Usage Guide

The AgentArea CLI has been enhanced with comprehensive authentication, chat functionality, and improved API integration.

## Installation & Setup

```bash
# Navigate to the project directory
cd /path/to/agentarea

# Install dependencies (if not already done)
pip install -r requirements.txt

# Make sure the API server is running
# In a separate terminal:
python -m core.apps.api.agentarea_api.main
```

## Authentication

### Login
```bash
# Login as a regular user
agentarea auth login

# Login as a specific user
agentarea auth login --user-id "john-doe"

# Login as an admin user
agentarea auth login --user-id "admin" --admin
```

### Check Authentication Status
```bash
agentarea auth status
```

### Logout
```bash
agentarea auth logout
```

## Chat with Agents

### Interactive Chat
```bash
# Start interactive chat with an agent
agentarea chat send AGENT_ID

# Example:
agentarea chat send "my-agent-123"
```

In interactive mode:
- Type your messages and press Enter
- Type `exit` or `quit` to end the conversation
- Type `clear` to start a new session
- Use Ctrl+C to exit

### Send Single Message
```bash
# Send a single message
agentarea chat send AGENT_ID --message "Hello, how are you?"

# With specific session ID
agentarea chat send AGENT_ID --message "Continue our conversation" --session-id "session-123"
```

### List Available Chat Agents
```bash
agentarea chat agents
```

## Agent Management

### List Agents
```bash
agentarea agent list
```

### Create Agent
```bash
agentarea agent create
```

## LLM Model Management

### List Models
```bash
agentarea llm list
```

### Create Model
```bash
agentarea llm create
```

## System Management

### Check System Status
```bash
agentarea system status
```

## Configuration

### Set API URL
```bash
# Set API URL for current command
agentarea --api-url "http://localhost:8080" auth status

# The URL will be saved and used for future commands
```

### Configuration Storage
The CLI stores configuration in `~/.agentarea/config.json`:
- Authentication tokens
- API URL
- User preferences

## Features

### 🔐 Authentication
- JWT token-based authentication
- Support for admin and regular user roles
- Persistent token storage
- Automatic token validation

### 💬 Interactive Chat
- Real-time conversation with agents
- Session management
- Multi-turn conversations
- Graceful error handling

### 🛠️ API Integration
- Full REST API integration
- Automatic authentication headers
- Comprehensive error handling
- Timeout management

### 📊 Management Commands
- Agent lifecycle management
- LLM model management
- System health monitoring
- Configuration management

## Error Handling

The CLI provides clear error messages for common issues:

- **Authentication Required**: `❌ Please login first with 'agentarea auth login'`
- **Connection Failed**: `❌ Cannot connect to API server at http://localhost:8000`
- **Invalid Token**: `❌ Authentication failed. Please login first`

## Examples

### Complete Workflow
```bash
# 1. Login
agentarea auth login --user-id "developer" --admin

# 2. Check system status
agentarea system status

# 3. List available agents
agentarea chat agents

# 4. Start chatting with an agent
agentarea chat send "helpful-assistant"
# > You: Hello! Can you help me with Python?
# > Agent: Of course! I'd be happy to help you with Python...
# > You: exit

# 5. Send a quick message
agentarea chat send "code-reviewer" --message "Please review this function: def hello(): return 'world'"

# 6. Check authentication status
agentarea auth status

# 7. Logout when done
agentarea auth logout
```

### Development & Testing
```bash
# Test CLI components
python test_cli.py

# Run with different API URL
agentarea --api-url "http://staging.agentarea.com" auth login

# Debug mode (if implemented)
DEBUG=1 agentarea chat send "debug-agent" --message "test"
```

## Troubleshooting

### Common Issues

1. **Import Errors**
   ```bash
   # Make sure you're in the correct directory
   cd /path/to/agentarea
   
   # Check Python path
   python -c "import sys; print(sys.path)"
   ```

2. **API Connection Issues**
   ```bash
   # Check if API server is running
   curl http://localhost:8000/api/v1/system/health
   
   # Check configured API URL
   agentarea auth status
   ```

3. **Authentication Issues**
   ```bash
   # Clear stored authentication
   agentarea auth logout
   
   # Login again
   agentarea auth login
   ```

4. **Configuration Issues**
   ```bash
   # Check configuration file
   cat ~/.agentarea/config.json
   
   # Reset configuration
   rm -rf ~/.agentarea
   ```

## Advanced Usage

### Scripting
```bash
#!/bin/bash
# Automated agent interaction script

# Login
agentarea auth login --user-id "script-user"

# Send multiple messages
for message in "Hello" "How are you?" "Goodbye"; do
    agentarea chat send "my-agent" --message "$message"
    sleep 1
done

# Logout
agentarea auth logout
```

### Integration with CI/CD
```yaml
# GitHub Actions example
- name: Test AgentArea CLI
  run: |
    agentarea auth login --user-id "ci-user"
    agentarea system status
    agentarea chat agents
    agentarea auth logout
```

This enhanced CLI provides a complete interface for interacting with the AgentArea API, making it easy to test endpoints, manage resources, and chat with agents from the command line.