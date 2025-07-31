# Contributing to AgentArea

## 🎯 Welcome Contributors

Thank you for your interest in contributing to AgentArea! This guide will help you understand our development process, coding standards, and how to submit contributions effectively.

## 🚀 Quick Start for Contributors

### 1. Development Setup
```bash
# Fork and clone the repository
git clone https://github.com/your-username/agentarea.git
cd agentarea

# Set up development environment
cp core/docs/env.example .env
docker compose -f docker-compose.dev.yaml up -d

# Verify setup
curl http://localhost:8000/health
```

### 2. Create Feature Branch
```bash
# Create and switch to feature branch
git checkout -b feature/your-feature-name

# Or for bug fixes
git checkout -b fix/issue-description
```

### 3. Make Changes
- Follow our [coding standards](#coding-standards)
- Write tests for new functionality
- Update documentation as needed

### 4. Submit Pull Request
- Push your branch to your fork
- Create a pull request with clear description
- Ensure all checks pass

## 📋 Development Workflow

### Branch Naming Convention
```
feature/feature-name        # New features
fix/bug-description         # Bug fixes
refactor/component-name     # Code refactoring
docs/documentation-update   # Documentation changes
chore/maintenance-task      # Maintenance tasks
```

### Commit Message Format
```
type(scope): brief description

[optional body]

[optional footer]
```

**Types:**
- `feat`: New feature
- `fix`: Bug fix
- `docs`: Documentation changes
- `style`: Code style changes (formatting, etc.)
- `refactor`: Code refactoring
- `test`: Adding or updating tests
- `chore`: Maintenance tasks

**Examples:**
```
feat(agents): add streaming chat support

Implement server-sent events for real-time chat responses.
Includes WebSocket fallback for older browsers.

Closes #123
```

```
fix(mcp): resolve server startup race condition

Ensure MCP servers wait for database connection before starting.
```

### Pull Request Process

1. **Pre-submission Checklist:**
   - [ ] Code follows style guidelines
   - [ ] Tests pass locally
   - [ ] Documentation updated
   - [ ] No merge conflicts
   - [ ] Descriptive commit messages

2. **PR Description Template:**
   ```markdown
   ## Description
   Brief description of changes
   
   ## Type of Change
   - [ ] Bug fix
   - [ ] New feature
   - [ ] Breaking change
   - [ ] Documentation update
   
   ## Testing
   - [ ] Unit tests pass
   - [ ] Integration tests pass
   - [ ] Manual testing completed
   
   ## Related Issues
   Closes #issue-number
   ```

3. **Review Process:**
   - At least one code review required
   - All CI checks must pass
   - Documentation review for user-facing changes
   - Security review for auth/permission changes

## 🔧 Coding Standards

### Python Code Style

**Formatting:**
- Use `black` for code formatting
- Use `isort` for import sorting
- Use `ruff` for linting

```bash
# Format code
docker compose -f docker-compose.dev.yaml exec app black .
docker compose -f docker-compose.dev.yaml exec app isort .

# Check linting
docker compose -f docker-compose.dev.yaml exec app ruff check .
```

**Code Quality:**
- Maximum line length: 88 characters
- Use type hints for all function parameters and return values
- Follow PEP 8 naming conventions
- Use docstrings for all public functions and classes

**Example:**
```python
from typing import Optional, List
from pydantic import BaseModel

class AgentConfig(BaseModel):
    """Configuration for AI agents.
    
    Attributes:
        model: The LLM model to use
        temperature: Sampling temperature (0.0-1.0)
        max_tokens: Maximum tokens in response
    """
    model: str
    temperature: float = 0.7
    max_tokens: Optional[int] = None

def create_agent(
    name: str, 
    config: AgentConfig,
    user_id: Optional[str] = None
) -> Agent:
    """Create a new AI agent.
    
    Args:
        name: Human-readable agent name
        config: Agent configuration
        user_id: ID of creating user
        
    Returns:
        Created agent instance
        
    Raises:
        ValidationError: If config is invalid
    """
    # Implementation here
    pass
```

### Database Patterns

**Migrations:**
```bash
# Create new migration
docker compose -f docker-compose.dev.yaml run --rm app alembic revision --autogenerate -m "descriptive message"

# Review generated migration before committing
# Test migration up and down
docker compose -f docker-compose.dev.yaml run --rm app alembic upgrade head
docker compose -f docker-compose.dev.yaml run --rm app alembic downgrade -1
```

**Model Conventions:**
```python
from sqlalchemy import Column, String, DateTime, ForeignKey
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
from core.database.base import BaseModel

class Agent(BaseModel):
    """AI Agent model."""
    __tablename__ = "agents"
    
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    created_by = Column(UUID(as_uuid=True), ForeignKey("users.id"), nullable=False)
    
    # Relationships
    creator = relationship("User", back_populates="agents")
    
    def __repr__(self) -> str:
        return f"<Agent(id={self.id}, name='{self.name}')>"
```

### API Design

**Endpoint Conventions:**
```python
from fastapi import APIRouter, Depends, HTTPException, status
from typing import List
from core.auth import get_current_user
from core.schemas import AgentCreate, AgentResponse

router = APIRouter(prefix="/v1/agents", tags=["agents"])

@router.post("/", response_model=AgentResponse, status_code=status.HTTP_201_CREATED)
async def create_agent(
    agent_data: AgentCreate,
    current_user: User = Depends(get_current_user)
) -> AgentResponse:
    """Create a new agent.
    
    Args:
        agent_data: Agent creation data
        current_user: Authenticated user
        
    Returns:
        Created agent data
        
    Raises:
        HTTPException: If creation fails
    """
    try:
        agent = await agent_service.create(agent_data, current_user.id)
        return AgentResponse.from_orm(agent)
    except ValidationError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
```

**Response Patterns:**
```python
# Success responses
{
    "id": "agent-123",
    "name": "chat-assistant",
    "created_at": "2025-01-XX T XX:XX:XX.XXXZ"
}

# Error responses
{
    "error": {
        "code": "VALIDATION_ERROR",
        "message": "Invalid agent configuration",
        "details": {
            "field": "temperature",
            "issue": "Must be between 0.0 and 1.0"
        }
    }
}

# List responses
{
    "items": [...],
    "total": 42,
    "limit": 20,
    "offset": 0
}
```

### Frontend Code Style (Future)

**TypeScript/React:**
- Use TypeScript for all new code
- Follow React functional component patterns
- Use React hooks for state management
- Implement proper error boundaries

## 🧪 Testing Guidelines

### Test Structure
```
tests/
├── unit/           # Unit tests
├── integration/    # Integration tests
├── e2e/           # End-to-end tests
└── fixtures/      # Test data and fixtures
```

### Writing Tests

**Unit Tests:**
```python
import pytest
from unittest.mock import Mock, patch
from core.services.agent_service import AgentService
from core.schemas import AgentCreate

class TestAgentService:
    """Test cases for AgentService."""
    
    @pytest.fixture
    def agent_service(self):
        return AgentService()
    
    @pytest.fixture
    def sample_agent_data(self):
        return AgentCreate(
            name="test-agent",
            type="chat",
            config={"model": "gpt-4"}
        )
    
    async def test_create_agent_success(self, agent_service, sample_agent_data):
        """Test successful agent creation."""
        with patch('core.database.agent_repository.create') as mock_create:
            mock_create.return_value = Mock(id="agent-123")
            
            result = await agent_service.create(sample_agent_data, "user-456")
            
            assert result.id == "agent-123"
            mock_create.assert_called_once()
    
    async def test_create_agent_validation_error(self, agent_service):
        """Test agent creation with invalid data."""
        invalid_data = AgentCreate(name="", type="invalid")
        
        with pytest.raises(ValidationError):
            await agent_service.create(invalid_data, "user-456")
```

**Integration Tests:**
```python
import pytest
from httpx import AsyncClient
from core.main import app

@pytest.mark.asyncio
class TestAgentAPI:
    """Integration tests for Agent API."""
    
    async def test_create_agent_endpoint(self, client: AsyncClient, auth_headers):
        """Test agent creation endpoint."""
        agent_data = {
            "name": "test-agent",
            "type": "chat",
            "config": {"model": "gpt-4"}
        }
        
        response = await client.post(
            "/v1/agents/",
            json=agent_data,
            headers=auth_headers
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "test-agent"
        assert "id" in data
```

### Running Tests
```bash
# Run all tests
docker compose -f docker-compose.dev.yaml exec app pytest

# Run specific test file
docker compose -f docker-compose.dev.yaml exec app pytest tests/unit/test_agents.py

# Run with coverage
docker compose -f docker-compose.dev.yaml exec app pytest --cov=core

# Run integration tests
docker compose -f docker-compose.dev.yaml exec app pytest tests/integration/
```

## 📚 Documentation Standards

### Code Documentation
- Use docstrings for all public functions, classes, and modules
- Include type hints in function signatures
- Document complex algorithms and business logic
- Keep comments up-to-date with code changes

### API Documentation
- Use FastAPI automatic documentation
- Provide clear endpoint descriptions
- Include request/response examples
- Document error conditions

### User Documentation
- Write clear, concise instructions
- Include code examples
- Provide troubleshooting steps
- Keep documentation current with features

## 🔒 Security Guidelines

### Authentication & Authorization
- Never commit secrets or API keys
- Use environment variables for configuration
- Implement proper input validation
- Follow principle of least privilege

### Data Protection
- Sanitize user inputs
- Use parameterized queries
- Implement rate limiting
- Log security events

### Code Security
```python
# Good: Parameterized query
result = await database.fetch_all(
    "SELECT * FROM agents WHERE user_id = :user_id",
    {"user_id": user_id}
)

# Bad: String interpolation (SQL injection risk)
result = await database.fetch_all(
    f"SELECT * FROM agents WHERE user_id = '{user_id}'"
)
```

## 🚀 Performance Guidelines

### Database Optimization
- Use appropriate indexes
- Implement query pagination
- Avoid N+1 query problems
- Use database connection pooling

### API Performance
- Implement caching where appropriate
- Use async/await for I/O operations
- Optimize serialization
- Monitor response times

### Resource Management
- Clean up resources properly
- Use context managers
- Implement proper error handling
- Monitor memory usage

## 🔄 Release Process

### Version Numbering
- Follow Semantic Versioning (SemVer)
- Format: `MAJOR.MINOR.PATCH`
- Tag releases in Git

### Release Checklist
- [ ] All tests pass
- [ ] Documentation updated
- [ ] Migration scripts tested
- [ ] Security review completed
- [ ] Performance impact assessed
- [ ] Rollback plan prepared

## 🆘 Getting Help

### Resources
- **[Getting Started](GETTING_STARTED.md)** - Setup guide
- **[API Reference](API_REFERENCE.md)** - API documentation
- **[Troubleshooting](TROUBLESHOOTING.md)** - Common issues
- **[Architecture Docs](../core/docs/SYSTEM_ARCHITECTURE.md)** - Technical details

### Support Channels
- **Code Reviews**: Submit pull requests
- **Questions**: Create GitHub issues
- **Discussions**: Team chat/meetings
- **Documentation**: Update relevant docs

## 📋 Contributor Recognition

We appreciate all contributions to AgentArea! Contributors will be:
- Listed in project documentation
- Recognized in release notes
- Invited to contributor discussions
- Eligible for maintainer roles

---

*Contributing guidelines last updated: January 2025*
*Thank you for helping make AgentArea better! 🚀*