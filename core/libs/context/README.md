# AgentArea Context Management

A flexible context management system for AgentArea that provides hierarchical memory storage and retrieval for AI agents.

## Features

- **Hierarchical Context**: Support for user, task, and agent-level context scoping
- **Flexible Storage**: Pluggable provider architecture supporting FAISS and future backends
- **Semantic Search**: Vector-based similarity search for context retrieval
- **Multiple Context Types**: Working, factual, episodic, and semantic memory types
- **Easy Integration**: Clean DI-based integration with existing AgentArea services

## Quick Start

```python
from agentarea_context import ContextService
from agentarea_context.infrastructure.di_container import setup_context_di
from agentarea_common.di.container import DIContainer

# Setup DI
container = DIContainer()
setup_context_di(container)
context_service = container.get(ContextService)

# Store context
await context_service.store_context(
    "User prefers detailed technical explanations",
    user_id=user_id,
    task_id=task_id
)

# Retrieve context
contexts = await context_service.get_context(
    query="user communication style",
    user_id=user_id,
    limit=5
)
```

## Context Hierarchy

The system supports flexible context scoping:

1. **Global**: Available to all agents
2. **Agent-specific**: Personal to a particular agent
3. **User-specific**: Associated with a specific user
4. **Task-specific**: Related to a specific task/conversation thread

## Configuration

Configure via environment variables:

```bash
CONTEXT_PROVIDER=faiss
CONTEXT_EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
CONTEXT_FAISS_INDEX_PATH=./data/context_index.faiss
```

## Providers

### FAISS Provider
- Local vector storage with FAISS
- No external dependencies
- Perfect for development and small-scale deployments

### Future Providers
- Qdrant integration
- PostgreSQL with pgvector
- Redis vector search
- Mem0 self-hosted integration

## Development

```bash
# Install dependencies
uv sync

# Run tests
uv run pytest libs/agentarea-context/tests/

# Lint
uv run ruff check libs/agentarea-context/
```