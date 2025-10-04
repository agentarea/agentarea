from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from agentarea_context.application.context_service import ContextService
from agentarea_context.domain.enums import ContextType
from agentarea_context.domain.models import Context


@pytest.fixture
def mock_context_provider():
    return AsyncMock()


@pytest.fixture
def context_service(mock_context_provider):
    return ContextService(mock_context_provider)


@pytest.mark.asyncio
async def test_store_context(context_service, mock_context_provider):
    user_id = uuid4()
    task_id = uuid4()
    agent_id = uuid4()
    content = "User prefers detailed explanations"

    expected_context_id = uuid4()
    mock_context_provider.store_context.return_value = expected_context_id

    result = await context_service.store_context(
        content=content,
        context_type=ContextType.FACTUAL,
        user_id=user_id,
        task_id=task_id,
        agent_id=agent_id,
    )

    assert result == expected_context_id
    mock_context_provider.store_context.assert_called_once_with(
        content=content,
        context_type=ContextType.FACTUAL,
        user_id=user_id,
        task_id=task_id,
        agent_id=agent_id,
        metadata={},
    )


@pytest.mark.asyncio
async def test_get_context(context_service, mock_context_provider):
    user_id = uuid4()
    query = "user preferences"

    expected_contexts = [
        Context(
            id=uuid4(),
            content="User likes brief responses",
            context_type=ContextType.FACTUAL,
            user_id=user_id,
            score=0.8,
        )
    ]
    mock_context_provider.get_context.return_value = expected_contexts

    result = await context_service.get_context(query=query, user_id=user_id, limit=5)

    assert result == expected_contexts
    mock_context_provider.get_context.assert_called_once_with(
        query=query, user_id=user_id, task_id=None, agent_id=None, limit=5
    )


@pytest.mark.asyncio
async def test_get_combined_context(context_service, mock_context_provider):
    user_id = uuid4()
    task_id = uuid4()
    agent_id = uuid4()
    query = "API integration"

    # Mock different context types
    task_context = Context(
        id=uuid4(),
        content="This task involves REST API",
        context_type=ContextType.FACTUAL,
        user_id=user_id,
        task_id=task_id,
        score=0.9,
    )

    user_context = Context(
        id=uuid4(),
        content="User prefers JSON examples",
        context_type=ContextType.FACTUAL,
        user_id=user_id,
        score=0.7,
    )

    agent_context = Context(
        id=uuid4(),
        content="I'm good at API documentation",
        context_type=ContextType.SEMANTIC,
        agent_id=agent_id,
        score=0.6,
    )

    # Configure mock to return different contexts based on call parameters
    def mock_get_context(query, user_id=None, task_id=None, agent_id=None, limit=10):
        if task_id:
            return [task_context]
        elif user_id and not task_id:
            return [user_context]
        elif agent_id:
            return [agent_context]
        return []

    mock_context_provider.get_context.side_effect = mock_get_context

    result = await context_service.get_combined_context(
        user_id=user_id, task_id=task_id, agent_id=agent_id, query=query, limit=10
    )

    # Should return all contexts, sorted by score (highest first)
    assert len(result) == 3
    assert result[0] == task_context  # Highest score (0.9)
    assert result[1] == user_context  # Second highest (0.7)
    assert result[2] == agent_context  # Lowest (0.6)


@pytest.mark.asyncio
async def test_get_combined_context_deduplication(context_service, mock_context_provider):
    user_id = uuid4()
    task_id = uuid4()
    agent_id = uuid4()
    query = "API integration"

    # Same context appearing in multiple scopes (should be deduplicated)
    duplicate_context = Context(
        id=uuid4(),
        content="API rate limiting required",
        context_type=ContextType.FACTUAL,
        user_id=user_id,
        score=0.8,
    )

    def mock_get_context(query, user_id=None, task_id=None, agent_id=None, limit=10):
        # Return same context for different scopes
        return [duplicate_context]

    mock_context_provider.get_context.side_effect = mock_get_context

    result = await context_service.get_combined_context(
        user_id=user_id, task_id=task_id, agent_id=agent_id, query=query, limit=10
    )

    # Should return only one instance despite multiple calls
    assert len(result) == 1
    assert result[0] == duplicate_context
