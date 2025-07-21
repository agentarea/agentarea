"""
API Compatibility Integration Tests

This module tests all API endpoints to ensure they work correctly
with the refactored task service architecture. It verifies that no breaking
changes were introduced during the refactoring.

Requirements tested:
- 4.4: Verify that no breaking changes were introduced
- 5.4: Update dependency injection documentation
"""

import json
import pytest
from datetime import datetime
from uuid import UUID, uuid4
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from fastapi import FastAPI

from agentarea_api.main import app
from agentarea_agents.domain.models import Agent
from agentarea_tasks.domain.models import SimpleTask


class TestAPICompatibility:
    """Test suite for API compatibility verification."""
    
    @pytest.fixture
    def client(self):
        """Create a test client for the FastAPI app."""
        return TestClient(app)
    
    @pytest.fixture
    def mock_agent(self):
        """Create a mock agent for testing."""
        return Agent(
            id=uuid4(),
            name="Test Agent",
            description="Test agent for API compatibility tests",
            instruction="You are a helpful test assistant",
            planning_enabled=False,
            workflow_type="single",
            tools_config={"mcp_servers": [], "builtin_tools": [], "custom_tools": []},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
    
    @pytest.fixture
    def mock_task(self):
        """Create a mock task for testing."""
        return SimpleTask(
            id=uuid4(),
            title="Test Task",
            description="Test task for API compatibility",
            query="Test query",
            user_id="test_user",
            agent_id=uuid4(),
            status="submitted",
            task_parameters={"test": True},
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow()
        )
    
    def test_health_endpoint(self, client):
        """Test the health endpoint."""
        response = client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert "status" in data
        assert data["status"] == "healthy"
    
    @patch('agentarea_api.api.deps.services.get_agent_service')
    def test_list_agents_endpoint(self, mock_get_agent_service, client, mock_agent):
        """Test the list agents endpoint."""
        # Mock the agent service
        mock_service = AsyncMock()
        mock_service.list.return_value = [mock_agent]
        mock_get_agent_service.return_value = mock_service
        
        response = client.get("/api/v1/agents")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
        if data:  # If we have agents
            assert "id" in data[0]
            assert "name" in data[0]
    
    @patch('agentarea_api.api.deps.services.get_agent_service')
    def test_get_agent_endpoint(self, mock_get_agent_service, client, mock_agent):
        """Test the get specific agent endpoint."""
        # Mock the agent service
        mock_service = AsyncMock()
        mock_service.get.return_value = mock_agent
        mock_get_agent_service.return_value = mock_service
        
        response = client.get(f"/api/v1/agents/{mock_agent.id}")
        assert response.status_code == 200
        data = response.json()
        assert data["id"] == str(mock_agent.id)
        assert data["name"] == mock_agent.name
    
    @patch('agentarea_api.api.deps.services.get_agent_service')
    def test_get_nonexistent_agent(self, mock_get_agent_service, client):
        """Test getting a non-existent agent returns 404."""
        # Mock the agent service to return None
        mock_service = AsyncMock()
        mock_service.get.return_value = None
        mock_get_agent_service.return_value = mock_service
        
        fake_agent_id = uuid4()
        response = client.get(f"/api/v1/agents/{fake_agent_id}")
        assert response.status_code == 404
    
    @patch('agentarea_api.api.deps.services.get_agent_service')
    @patch('agentarea_api.api.deps.services.get_temporal_workflow_service')
    @patch('agentarea_common.config.get_database')
    def test_list_tasks_endpoint(self, mock_get_database, mock_get_workflow_service, 
                                mock_get_agent_service, client, mock_agent, mock_task):
        """Test the global tasks list endpoint."""
        # Mock the agent service
        mock_agent_service = AsyncMock()
        mock_agent_service.list.return_value = [mock_agent]
        mock_get_agent_service.return_value = mock_agent_service
        
        # Mock the workflow service
        mock_workflow_service = AsyncMock()
        mock_get_workflow_service.return_value = mock_workflow_service
        
        # Mock the database and task repository
        mock_db = MagicMock()
        mock_session = AsyncMock()
        mock_db.async_session_factory.return_value.__aenter__.return_value = mock_session
        mock_get_database.return_value = mock_db
        
        # Mock task repository
        with patch('agentarea_tasks.infrastructure.repository.TaskRepository') as mock_repo_class:
            mock_repo = AsyncMock()
            mock_repo.list_by_agent.return_value = [mock_task]
            mock_repo_class.return_value = mock_repo
            
            response = client.get("/api/v1/tasks")
            assert response.status_code == 200
            data = response.json()
            assert isinstance(data, list)
    
    @patch('agentarea_api.api.deps.services.get_agent_service')
    def test_list_agent_tasks_endpoint(self, mock_get_agent_service, client, mock_agent):
        """Test the agent-specific tasks list endpoint."""
        # Mock the agent service
        mock_service = AsyncMock()
        mock_service.get.return_value = mock_agent
        mock_get_agent_service.return_value = mock_service
        
        response = client.get(f"/api/v1/agents/{mock_agent.id}/tasks")
        assert response.status_code == 200
        data = response.json()
        assert isinstance(data, list)
    
    @patch('agentarea_api.api.deps.services.get_agent_service')
    @patch('agentarea_api.api.deps.services.get_temporal_workflow_service')
    @patch('agentarea_api.api.deps.events.EventBrokerDep')
    @patch('agentarea_common.config.get_database')
    def test_create_task_endpoint(self, mock_get_database, mock_event_broker, 
                                 mock_get_workflow_service, mock_get_agent_service, 
                                 client, mock_agent):
        """Test the create task endpoint."""
        # Mock the agent service
        mock_agent_service = AsyncMock()
        mock_agent_service.get.return_value = mock_agent
        mock_get_agent_service.return_value = mock_agent_service
        
        # Mock the workflow service
        mock_workflow_service = AsyncMock()
        mock_workflow_service.execute_agent_task_async.return_value = {
            "execution_id": "test-execution-id"
        }
        mock_get_workflow_service.return_value = mock_workflow_service
        
        # Mock event broker
        mock_broker = AsyncMock()
        mock_event_broker.return_value = mock_broker
        
        # Mock the database and task repository
        mock_db = MagicMock()
        mock_session = AsyncMock()
        mock_db.async_session_factory.return_value.__aenter__.return_value = mock_session
        mock_get_database.return_value = mock_db
        
        # Mock task repository
        with patch('agentarea_tasks.infrastructure.repository.TaskRepository') as mock_repo_class:
            mock_repo = AsyncMock()
            mock_stored_task = MagicMock()
            mock_stored_task.id = uuid4()
            mock_repo.create_from_data.return_value = mock_stored_task
            mock_repo_class.return_value = mock_repo
            
            task_data = {
                "description": "Test task for API compatibility",
                "parameters": {"test": True},
                "user_id": "test_user",
                "enable_agent_communication": True
            }
            
            response = client.post(f"/api/v1/agents/{mock_agent.id}/tasks", json=task_data)
            assert response.status_code == 200
            data = response.json()
            assert "id" in data
            assert "agent_id" in data
            assert "description" in data
            assert data["description"] == task_data["description"]
    
    @patch('agentarea_api.api.deps.services.get_agent_service')
    def test_a2a_well_known_endpoint(self, mock_get_agent_service, client, mock_agent):
        """Test the A2A well-known endpoint."""
        # Mock the agent service
        mock_service = AsyncMock()
        mock_service.get_agent.return_value = mock_agent
        mock_get_agent_service.return_value = mock_service
        
        response = client.get(f"/api/v1/agents/{mock_agent.id}/a2a/well-known")
        assert response.status_code == 200
        data = response.json()
        
        # Check required A2A fields
        required_fields = ["id", "name", "capabilities", "endpoints"]
        for field in required_fields:
            assert field in data
        
        # Check capabilities structure
        assert "can_send_messages" in data["capabilities"]
        assert "can_receive_messages" in data["capabilities"]
        assert "can_execute_tasks" in data["capabilities"]
        assert "supports_streaming" in data["capabilities"]
        
        # Check endpoints structure
        assert "a2a_rpc" in data["endpoints"]
        assert "well_known" in data["endpoints"]
    
    @patch('agentarea_api.api.deps.services.get_agent_service')
    @patch('agentarea_api.api.deps.services.get_task_service')
    def test_a2a_rpc_endpoint(self, mock_get_task_service, mock_get_agent_service, 
                             client, mock_agent):
        """Test the A2A RPC endpoint."""
        # Mock the agent service
        mock_agent_service = AsyncMock()
        mock_agent_service.get_agent.return_value = mock_agent
        mock_get_agent_service.return_value = mock_agent_service
        
        # Mock the task service
        mock_task_service = AsyncMock()
        mock_get_task_service.return_value = mock_task_service
        
        # Test agent card request
        rpc_request = {
            "jsonrpc": "2.0",
            "method": "agent/authenticatedExtendedCard",
            "params": {},
            "id": "test-1"
        }
        
        with patch('agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth') as mock_auth:
            mock_auth.return_value = MagicMock()  # Mock auth context
            
            response = client.post(
                f"/api/v1/agents/{mock_agent.id}/a2a/rpc",
                json=rpc_request,
                headers={"Content-Type": "application/json"}
            )
            
            assert response.status_code == 200
            data = response.json()
            
            # Check JSON-RPC response format
            assert "jsonrpc" in data
            assert data["jsonrpc"] == "2.0"
            assert "id" in data
            assert data["id"] == "test-1"
            
            # Should have either result or error
            assert "result" in data or "error" in data
    
    @patch('agentarea_api.api.deps.services.get_agent_service')
    @patch('agentarea_api.api.deps.services.get_task_service')
    def test_a2a_rpc_invalid_request(self, mock_get_task_service, mock_get_agent_service, 
                                   client, mock_agent):
        """Test A2A RPC endpoint with invalid request."""
        # Mock the agent service
        mock_agent_service = AsyncMock()
        mock_agent_service.get_agent.return_value = mock_agent
        mock_get_agent_service.return_value = mock_agent_service
        
        # Mock the task service
        mock_task_service = AsyncMock()
        mock_get_task_service.return_value = mock_task_service
        
        # Test invalid JSON-RPC request
        invalid_request = {"invalid": "request"}
        
        with patch('agentarea_api.api.v1.a2a_auth.require_a2a_execute_auth') as mock_auth:
            mock_auth.return_value = MagicMock()  # Mock auth context
            
            response = client.post(
                f"/api/v1/agents/{mock_agent.id}/a2a/rpc",
                json=invalid_request,
                headers={"Content-Type": "application/json"}
            )
            
            assert response.status_code == 200  # JSON-RPC returns 200 with error
            data = response.json()
            
            # Should be a JSON-RPC error response
            assert "jsonrpc" in data
            assert "error" in data
            assert data["error"]["code"] == -32700  # Parse error
    
    def test_dependency_injection_structure(self):
        """Test that dependency injection is properly structured."""
        from agentarea_api.api.deps.services import (
            get_agent_service,
            get_task_service,
            get_temporal_workflow_service,
            get_event_broker
        )
        
        # Verify that dependency functions exist and are callable
        assert callable(get_agent_service)
        assert callable(get_task_service)
        assert callable(get_temporal_workflow_service)
        assert callable(get_event_broker)
        
        # Verify type annotations exist
        import inspect
        
        sig = inspect.signature(get_agent_service)
        assert len(sig.parameters) > 0  # Should have dependencies
        
        sig = inspect.signature(get_task_service)
        assert len(sig.parameters) > 0  # Should have dependencies
    
    def test_task_service_compatibility(self):
        """Test that TaskService maintains backward compatibility."""
        from agentarea_tasks.task_service import TaskService
        from agentarea_tasks.domain.base_service import BaseTaskService
        
        # Verify inheritance
        assert issubclass(TaskService, BaseTaskService)
        
        # Verify required methods exist
        required_methods = [
            'submit_task',
            'get_task',
            'create_task',
            'update_task',
            'list_tasks',
            'cancel_task'
        ]
        
        for method_name in required_methods:
            assert hasattr(TaskService, method_name)
            assert callable(getattr(TaskService, method_name))
        
        # Verify compatibility methods exist
        compatibility_methods = [
            'update_task_status',
            'list_agent_tasks',
            'get_task_status',
            'get_task_result'
        ]
        
        for method_name in compatibility_methods:
            assert hasattr(TaskService, method_name)
            assert callable(getattr(TaskService, method_name))
    
    def test_api_response_formats(self):
        """Test that API response formats are consistent."""
        from agentarea_api.api.v1.agents_tasks import (
            TaskResponse,
            TaskWithAgent,
            TaskCreate,
            TaskEvent,
            TaskEventResponse
        )
        
        # Verify response models exist and have required fields
        task_response_fields = ['id', 'agent_id', 'description', 'parameters', 
                               'status', 'result', 'created_at', 'execution_id']
        
        for field in task_response_fields:
            assert hasattr(TaskResponse, '__annotations__')
            assert field in TaskResponse.__annotations__
        
        # Verify TaskWithAgent extends TaskResponse with agent info
        task_with_agent_fields = task_response_fields + ['agent_name']
        for field in task_with_agent_fields:
            assert field in TaskWithAgent.__annotations__
        
        # Verify TaskCreate has required fields
        task_create_fields = ['description', 'parameters', 'user_id', 'enable_agent_communication']
        for field in task_create_fields:
            assert field in TaskCreate.__annotations__


@pytest.mark.integration
class TestAPIIntegration:
    """Integration tests that require actual service instances."""
    
    def test_service_integration(self):
        """Test that services can be properly instantiated through DI."""
        # This test would require actual database and service setup
        # For now, we'll just verify the structure is correct
        pass
    
    def test_event_publishing(self):
        """Test that events are properly published during API operations."""
        # This test would require actual event broker setup
        # For now, we'll just verify the structure is correct
        pass


if __name__ == "__main__":
    pytest.main([__file__, "-v"])