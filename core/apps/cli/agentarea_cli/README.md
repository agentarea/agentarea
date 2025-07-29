# AgentArea CLI

A command-line interface for managing AgentArea applications, agents, and LLM models.

## Installation

```bash
# Install from the core directory
cd core
pip install -e .
```

## Quick Start

```bash
# Login to AgentArea
agentarea auth login --user-id your-user-id

# Check authentication status
agentarea auth status

# List available agents
agentarea agent list

# Start a chat with an agent
agentarea chat send <agent-id> --message "Hello!"

# Check system status
agentarea system status
```

## Commands

### Authentication (`auth`)

- `login` - Login to AgentArea
- `logout` - Logout from AgentArea
- `status` - Check authentication status
- `config` - Manage configuration

### Agent Management (`agent`)

- `list` - List all agents
- `create` - Create a new agent
- `show` - Show agent details
- `update` - Update an existing agent
- `delete` - Delete an agent

### Chat (`chat`)

- `send` - Send messages to agents
- `agents` - List available chat agents
- `history` - View chat history
- `clear` - Clear chat history

### LLM Management (`llm`)

- `list` - List LLM models
- `create` - Create a new LLM model
- `show` - Show model details
- `update` - Update an existing model
- `delete` - Delete a model
- `test` - Test a model with a prompt
- `providers` - List available providers

### System (`system`)

- `status` - Check system health
- `info` - Show system information
- `logs` - View system logs
- `metrics` - Show system metrics
- `restart` - Restart system components
- `components` - List system components

## Configuration

The CLI stores configuration in `~/.agentarea/config.json`:

```json
{
  "api_url": "http://localhost:8000",
  "auth_token": "your-jwt-token",
  "debug": false
}
```

## Environment Variables

- `AGENTAREA_API_URL` - Override API URL
- `AGENTAREA_DEBUG` - Enable debug mode
- `AGENTAREA_CONFIG_DIR` - Override config directory

## Architecture

The CLI is organized into several modules:

- `main.py` - Main CLI entry point and command registration
- `config.py` - Configuration management
- `client.py` - HTTP client for API communication
- `exceptions.py` - Custom exception classes
- `utils.py` - Utility functions
- `commands/` - Individual command modules
  - `auth.py` - Authentication commands
  - `agent.py` - Agent management commands
  - `chat.py` - Chat commands
  - `llm.py` - LLM model commands
  - `system.py` - System management commands

## Error Handling

The CLI provides comprehensive error handling:

- Network connection errors
- Authentication failures
- API errors (4xx, 5xx)
- Configuration errors
- Validation errors

Use `--debug` flag for detailed error information.

## Development

### Adding New Commands

1. Create a new module in `commands/`
2. Define commands using Click decorators
3. Import and register in `main.py`
4. Add to `commands/__init__.py`

### Testing

```bash
# Run CLI tests
python -m pytest tests/cli/

# Test specific command
agentarea --debug auth status
```

## Examples

### Interactive Chat

```bash
# Start interactive chat session
agentarea chat send agent-123
# Type messages and press Enter
# Type 'exit' to quit
```

### Creating an Agent

```bash
agentarea agent create \
  --name "Assistant" \
  --description "A helpful assistant" \
  --instruction "You are a helpful AI assistant"
```

### Managing LLM Models

```bash
# List models
agentarea llm list --provider openai

# Create a model
agentarea llm create \
  --name "gpt-4" \
  --provider "openai" \
  --type "chat" \
  --api-key "your-key"

# Test a model
agentarea llm test model-123 --prompt "Hello, world!"
```