"""Integration tests for RepositoryFactory with real repositories."""

import pytest
from unittest.mock import AsyncMock

from .repository_factory import RepositoryFactory
from ..auth.context import UserContext


class TestRepositoryFactoryIntegration:
    """Integration test cases for RepositoryFactory with real repositories."""
    
    @pytest.fixture
    def mock_session(self):
        """Create a mock async session."""
        return AsyncMock()
    
    @pytest.fixture
    def user_context(self):
        """Create a test user context."""
        return UserContext(
            user_id="test-user",
            workspace_id="test-workspace",
            roles=["user"]
        )
    
    @pytest.fixture
    def factory(self, mock_session, user_context):
        """Create a repository factory instance."""
        return RepositoryFactory(mock_session, user_context)
    
    def test_create_task_repository(self, factory):
        """Test creating TaskRepository with factory."""
        try:
            from agentarea_tasks.infrastructure.repository import TaskRepository
            
            repo = factory.create_repository(TaskRepository)
            
            assert isinstance(repo, TaskRepository)
            assert repo.session == factory.session
            assert repo.user_context == factory.user_context
            assert repo.model_class.__name__ == "TaskORM"
            
        except ImportError:
            pytest.skip("TaskRepository not available")
    
    def test_create_agent_repository(self, factory):
        """Test creating AgentRepository with factory."""
        try:
            from agentarea_agents.infrastructure.repository import AgentRepository
            
            repo = factory.create_repository(AgentRepository)
            
            assert isinstance(repo, AgentRepository)
            assert repo.session == factory.session
            assert repo.user_context == factory.user_context
            
        except ImportError:
            pytest.skip("AgentRepository not available")
    
    def test_create_mcp_server_repository(self, factory):
        """Test creating MCPServerRepository with factory."""
        try:
            from agentarea_mcp.infrastructure.repository import MCPServerRepository
            
            repo = factory.create_repository(MCPServerRepository)
            
            assert isinstance(repo, MCPServerRepository)
            assert repo.session == factory.session
            assert repo.user_context == factory.user_context
            
        except ImportError:
            pytest.skip("MCPServerRepository not available")
    
    def test_create_mcp_server_instance_repository(self, factory):
        """Test creating MCPServerInstanceRepository with factory."""
        try:
            from agentarea_mcp.infrastructure.repository import MCPServerInstanceRepository
            
            repo = factory.create_repository(MCPServerInstanceRepository)
            
            assert isinstance(repo, MCPServerInstanceRepository)
            assert repo.session == factory.session
            assert repo.user_context == factory.user_context
            
        except ImportError:
            pytest.skip("MCPServerInstanceRepository not available")


if __name__ == "__main__":
    pytest.main([__file__])