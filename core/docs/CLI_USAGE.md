# AgentArea CLI Usage Guide

## Overview

The AgentArea CLI provides comprehensive command-line interface for managing LLMs, MCP servers, agents, and chat functionality. There are two CLI implementations available:

1. **`cli.py`** - Full-featured CLI integrated with the application
2. **`cli_simple.py`** - Simplified standalone CLI that works independently

## Installation & Setup

### Prerequisites
- Python 3.11+
- All dependencies installed: `pip install -r requirements.txt`
- Database properly configured and migrated

### Basic Setup
```bash
# Navigate to the core directory
cd core

# Run database migrations
python -m cli migrate

# Start the API server
python -m cli serve --host 0.0.0.0 --port 8000
```

## CLI Commands

### Server Management

```bash
# Start the API server
python -m cli serve --host 0.0.0.0 --port 8000 --reload

# Run database migrations
python -m cli migrate

# Check API server health (using simple CLI)
python cli_simple.py health

# Show available endpoints
python cli_simple.py endpoints
```

### LLM Management

#### List LLM Models and Instances
```bash
# List available LLM models
python -m cli llm models
# or
python cli_simple.py llm models

# List LLM model instances
python -m cli llm instances
# or  
python cli_simple.py llm instances
```

#### Create LLM Model
```bash
# Create a new LLM model
python -m cli llm create-model \
  --name "GPT-4" \
  --description "OpenAI GPT-4 model" \
  --provider "openai" \
  --model-type "chat" \
  --endpoint-url "https://api.openai.com/v1/chat/completions" \
  --context-window "8192" \
  --is-public

# Using simple CLI
python cli_simple.py llm create-model \
  --name "Claude-3" \
  --description "Anthropic Claude-3 model" \
  --provider "anthropic" \
  --model-type "chat" \
  --endpoint-url "https://api.anthropic.com/v1/messages" \
  --context-window "100000"
```

#### Create LLM Model Instance
```bash
# Create a new LLM model instance
python -m cli llm create-instance \
  --model-id "model-uuid-here" \
  --name "My GPT-4 Instance" \
  --description "Personal GPT-4 instance" \
  --api-key "your-api-key-here" \
  --is-public

# Using simple CLI  
python cli_simple.py llm create-instance \
  --model-id "model-uuid-here" \
  --name "My Claude Instance" \
  --description "Personal Claude instance" \
  --api-key "your-api-key-here"
```

### MCP Server Management

#### List MCP Servers and Instances
```bash
# List available MCP servers
python -m cli mcp servers
# or
python cli_simple.py mcp servers

# List MCP server instances
python -m cli mcp instances
# or
python cli_simple.py mcp instances
```

#### Create MCP Server
```bash
# Create a new MCP server
python -m cli mcp create-server \
  --name "File System MCP" \
  --description "MCP server for file system operations" \
  --docker-image "agentarea/mcp-filesystem:latest" \
  --version "1.0.0" \
  --tags "filesystem,files" \
  --is-public

# Using simple CLI
python cli_simple.py mcp create-server \
  --name "Database MCP" \
  --description "MCP server for database operations" \
  --docker-image "agentarea/mcp-database:latest" \
  --version "1.2.0" \
  --tags "database,sql"
```

#### Create MCP Server Instance
```bash
# Create a new MCP server instance
python -m cli mcp create-instance \
  --server-id "server-uuid-here" \
  --name "My File System MCP" \
  --endpoint-url "http://localhost:3001" \
  --config '{"root_path": "/home/user/documents"}'

# Using simple CLI
python cli_simple.py mcp create-instance \
  --server-id "server-uuid-here" \
  --name "My Database MCP" \
  --endpoint-url "http://localhost:3002" \
  --config '{"connection_string": "postgresql://user:pass@localhost/db"}'
```

### Agent Management

#### List and Create Agents
```bash
# List available agents
python -m cli agent list
# or
python cli_simple.py agent list

# Create a new agent
python -m cli agent create \
  --name "Research Assistant" \
  --description "An AI assistant specialized in research tasks" \
  --instruction "You are a helpful research assistant. Help users find and analyze information." \
  --model-id "llm-instance-uuid-here" \
  --planning

# Using simple CLI
python cli_simple.py agent create \
  --name "Code Assistant" \
  --description "An AI assistant for coding tasks" \
  --instruction "You are a helpful coding assistant. Help users write and debug code." \
  --model-id "llm-instance-uuid-here"
```

### Chat & Communication

#### Send Single Message
```bash
# Send a message to an agent
python -m cli chat send \
  --agent-id "agent-uuid-here" \
  --message "Hello, can you help me with a task?" \
  --session-id "optional-session-id"

# Using simple CLI
python cli_simple.py chat send \
  --agent-id "agent-uuid-here" \
  --message "What's the weather like today?" \
  --session-id "my-session-123"
```

#### Interactive Chat Session
```bash
# Start an interactive chat session
python -m cli chat interactive \
  --agent-id "agent-uuid-here"
```

## Configuration Options

### Environment Variables
```bash
# Database configuration
DATABASE_URL=postgresql://user:pass@localhost:5432/agentarea

# API server settings
API_HOST=0.0.0.0
API_PORT=8000

# LLM provider settings
OPENAI_API_KEY=your_openai_api_key
ANTHROPIC_API_KEY=your_anthropic_api_key

# MCP server settings
MCP_SERVER_TIMEOUT=30
MCP_MAX_CONCURRENT_REQUESTS=10
```

### Configuration Files
```bash
# Copy example configuration
cp config/example.env .env

# Edit configuration
nano .env
```

## Error Handling & Troubleshooting

### Common Issues

#### Database Connection Issues
```bash
# Check database connection
python -m cli health db

# Run migrations
python -m cli migrate

# Reset database (development only)
python -m cli db reset --confirm
```

#### API Server Issues
```bash
# Check server health
curl http://localhost:8000/health

# View server logs
python -m cli logs --tail 100

# Restart server with debug mode
python -m cli serve --debug --reload
```

#### CLI Command Issues
```bash
# Show help for specific command
python -m cli llm --help
python -m cli agent create --help

# Enable verbose logging
python -m cli --verbose llm models

# Use simple CLI for troubleshooting
python cli_simple.py health
```

## Advanced Usage

### Batch Operations
```bash
# Create multiple agents from config file
python -m cli agent create-batch --config agents.json

# Import LLM models from YAML
python -m cli llm import --file models.yaml

# Export current configuration
python -m cli export --output config_backup.json
```

### Integration with Scripts
```python
# Use CLI programmatically
from agentarea.cli import AgentAreaCLI

cli = AgentAreaCLI()
agents = await cli.list_agents()
print(f"Found {len(agents)} agents")
```

### Testing CLI Commands
```bash
# Test mode (dry run)
python -m cli --test-mode agent create \
  --name "Test Agent" \
  --description "Test agent for validation"

# Validate configuration
python -m cli validate --config .env
```

## API Documentation

For complete API documentation and advanced usage, see:
- API Documentation: `http://localhost:8000/docs`
- Project Summary: `PROJECT_SUMMARY.md` 
- System Architecture: `docs/SYSTEM_ARCHITECTURE.md` 