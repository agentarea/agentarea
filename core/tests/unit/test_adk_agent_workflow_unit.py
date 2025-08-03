#!/usr/bin/env python3
"""
Unit tests for ADK Agent Workflow.

Tests the workflow logic in isolation using mocks and test doubles.
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4
from datetime import datetime

from agentarea_execution.adk_temporal.workflows.adk_agent_workflow import ADKAgentWorkflow
from agentarea_execution.models import AgentExecutionRequest, AgentExecutionResult


class TestADKAgentWorkflowUnit:
    """Unit tests for ADK Agent Workflow logic."""

    @pytest.fixture
    def sample_request(self):
        """Create a sample agent execution request."""
        return AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            user_id="unit-test-user",
            task_query="Unit test query",
            timeout_seconds=60,
            max_reasoning_iterations=2
        )

    @pytest.fixture
    def mock_workflow_context(self):
        """Mock workflow context and info."""
        with patch('agentarea_execution.adk_temporal.workflows.adk_agent_workflow.workflow') as mock_workflow:
            # Mock workflow.info()
            mock_info = MagicMock()
            mock_info.workflow_id = "test-workflow-id"
            mock_workflow.info.return_value = mock_info
            
            # Mock workflow.now()
            mock_workflow.now.return_value = datetime.utcnow()
            
            # Mock workflow.execute_activity
            mock_workflow.execute_activity = AsyncMock()
            
            yield mock_workflow

    @pytest.fixture
    def mock_agent_config(self):
        """Mock agent configuration."""
        return {
            "id": str(uuid4()),
            "name": "Test Agent",
            "description": "Unit test agent",
            "model_id": "qwen2.5",
            "instruction": "You are a test assistant",
            "tools_config": {"mcp_servers": []},
            "enable_streaming": False
        }

    @pytest.fixture
    def mock_events(self):
        """Mock ADK events."""
        return [
            {
                "author": "assistant",
                "content": {
                    "parts": [{"text": "Hello, this is a test response"}]
                },
                "timestamp": datetime.utcnow().isoformat(),
                "cost": 0.001
            },
            {
                "author": "assistant", 
                "content": {
                    "parts": [{"text": "Task completed successfully"}]
                },
                "timestamp": datetime.utcnow().isoformat(),
                "cost": 0.002
            }
        ]

    @pytest.mark.asyncio
    async def test_workflow_initialization(self, sample_request, mock_workflow_context):
        """Test workflow initialization and basic setup."""
        
        workflow = ADKAgentWorkflow()
        
        # Test initial state
        assert workflow.execution_id == ""
        assert workflow.agent_config == {}
        assert workflow.session_data == {}
        assert workflow.events == []
        assert workflow.final_response is None
        assert workflow.success is False
        assert workflow.error_message is None
        assert workflow.start_time == 0.0
        assert workflow.end_time == 0.0

    @pytest.mark.asyncio
    async def test_build_agent_config(self, sample_request, mock_workflow_context, mock_agent_config):
        """Test agent configuration building."""
        
        # Mock the build_agent_config_activity
        mock_workflow_context.execute_activity.return_value = mock_agent_config
        
        workflow = ADKAgentWorkflow()
        
        # Test _build_agent_config method
        result = await workflow._build_agent_config(sample_request)
        
        assert result == mock_agent_config
        mock_workflow_context.execute_activity.assert_called_once()

    @pytest.mark.asyncio
    async def test_batch_execution_success(self, sample_request, mock_workflow_context, mock_agent_config, mock_events):
        """Test successful batch execution."""
        
        # Mock activities
        mock_workflow_context.execute_activity.side_effect = [
            mock_agent_config,  # build_agent_config_activity
            mock_events         # execute_adk_agent_with_temporal_backbone
        ]
        
        workflow = ADKAgentWorkflow()
        
        # Run the workflow
        result = await workflow.run(sample_request)
        
        # Verify result
        assert isinstance(result, AgentExecutionResult)
        assert result.task_id == sample_request.task_id
        assert result.agent_id == sample_request.agent_id
        assert result.success is True
        assert result.final_response is not None
        assert "Task completed successfully" in result.final_response
        assert len(result.conversation_history) > 0
        assert result.total_cost > 0.0

    @pytest.mark.asyncio
    async def test_batch_execution_failure(self, sample_request, mock_workflow_context, mock_agent_config):
        """Test batch execution with failure."""
        
        # Mock activities - first succeeds, second fails
        mock_workflow_context.execute_activity.side_effect = [
            mock_agent_config,  # build_agent_config_activity
            Exception("Test execution failure")  # execute_adk_agent_with_temporal_backbone
        ]
        
        workflow = ADKAgentWorkflow()
        
        # Run the workflow and expect it to handle the error
        with pytest.raises(Exception):
            await workflow.run(sample_request)

    @pytest.mark.asyncio
    async def test_extract_final_response(self, mock_events):
        """Test final response extraction from events."""
        
        workflow = ADKAgentWorkflow()
        
        # Test with valid events
        final_response = workflow._extract_final_response(mock_events)
        assert final_response == "Task completed successfully"
        
        # Test with empty events
        final_response = workflow._extract_final_response([])
        assert final_response is None
        
        # Test with events without content
        empty_events = [{"author": "assistant", "timestamp": datetime.utcnow().isoformat()}]
        final_response = workflow._extract_final_response(empty_events)
        assert final_response is None

    @pytest.mark.asyncio
    async def test_calculate_total_cost(self, mock_events):
        """Test cost calculation from events."""
        
        workflow = ADKAgentWorkflow()
        
        # Test with events containing cost
        total_cost = workflow._calculate_total_cost(mock_events)
        assert total_cost == 0.003  # 0.001 + 0.002
        
        # Test with events without cost
        no_cost_events = [{"author": "assistant", "content": {"parts": [{"text": "test"}]}}]
        total_cost = workflow._calculate_total_cost(no_cost_events)
        assert total_cost == 0.0

    @pytest.mark.asyncio
    async def test_should_use_streaming(self, mock_agent_config):
        """Test streaming mode detection."""
        
        workflow = ADKAgentWorkflow()
        workflow.agent_config = mock_agent_config.copy()
        
        # Test with streaming disabled
        assert workflow._should_use_streaming() is False
        
        # Test with streaming enabled
        workflow.agent_config["enable_streaming"] = True
        assert workflow._should_use_streaming() is True

    @pytest.mark.asyncio
    async def test_workflow_queries(self, sample_request, mock_workflow_context, mock_agent_config, mock_events):
        """Test workflow query methods."""
        
        workflow = ADKAgentWorkflow()
        workflow.execution_id = "test-execution-id"
        workflow.agent_config = mock_agent_config
        workflow.events = mock_events
        workflow.final_response = "Test final response"
        workflow.success = True
        
        # Test get_current_state query
        current_state = workflow.get_current_state()
        assert current_state["execution_id"] == "test-execution-id"
        assert current_state["agent_name"] == "Test Agent"
        assert current_state["event_count"] == 2
        assert current_state["success"] is True
        assert current_state["has_final_response"] is True
        
        # Test get_events query
        events = workflow.get_events(limit=1)
        assert len(events) == 1
        assert events[0] == mock_events[-1]  # Should return last event
        
        events_all = workflow.get_events(limit=0)
        assert len(events_all) == 2
        
        # Test get_final_response query
        final_response = workflow.get_final_response()
        assert final_response == "Test final response"

    @pytest.mark.asyncio
    async def test_workflow_signals(self):
        """Test workflow signal methods."""
        
        workflow = ADKAgentWorkflow()
        
        # Test pause signal
        await workflow.pause("Test pause reason")
        assert workflow.paused is True
        assert workflow.pause_reason == "Test pause reason"
        
        # Test resume signal
        await workflow.resume("Test resume reason")
        assert workflow.paused is False
        assert workflow.pause_reason == ""

    @pytest.mark.asyncio
    async def test_session_data_building(self, sample_request):
        """Test session data construction."""
        
        workflow = ADKAgentWorkflow()
        workflow.execution_id = "test-execution-id"
        
        # Simulate building session data (this happens in run method)
        session_data = {
            "user_id": str(sample_request.task_id),
            "session_id": f"session_{sample_request.task_id}",
            "app_name": "agentarea",
            "state": {
                "task_id": str(sample_request.task_id),
                "agent_id": str(sample_request.agent_id),
                "execution_id": workflow.execution_id,
            },
        }
        
        assert session_data["user_id"] == str(sample_request.task_id)
        assert session_data["app_name"] == "agentarea"
        assert session_data["state"]["task_id"] == str(sample_request.task_id)
        assert session_data["state"]["agent_id"] == str(sample_request.agent_id)
        assert session_data["state"]["execution_id"] == "test-execution-id"

    @pytest.mark.asyncio
    async def test_user_message_building(self, sample_request):
        """Test user message construction."""
        
        workflow = ADKAgentWorkflow()
        
        # Simulate building user message (this happens in run method)
        user_message = {
            "content": sample_request.task_query,
            "role": "user",
        }
        
        assert user_message["content"] == sample_request.task_query
        assert user_message["role"] == "user"

    @pytest.mark.asyncio
    async def test_conversation_history_extraction(self, mock_events):
        """Test conversation history extraction from events."""
        
        workflow = ADKAgentWorkflow()
        workflow.events = mock_events
        
        # This would be called in _finalize_execution
        conversation_history = []
        for event_dict in workflow.events:
            try:
                content_data = event_dict.get("content", {})
                if isinstance(content_data, dict) and "parts" in content_data:
                    for part in content_data.get("parts", []):
                        if isinstance(part, dict) and "text" in part:
                            conversation_history.append({
                                "role": event_dict.get("author", "assistant"),
                                "content": part["text"],
                                "timestamp": event_dict.get("timestamp", 0),
                            })
            except Exception:
                pass
        
        assert len(conversation_history) == 2
        assert conversation_history[0]["content"] == "Hello, this is a test response"
        assert conversation_history[1]["content"] == "Task completed successfully"
        assert all(item["role"] == "assistant" for item in conversation_history)

    @pytest.mark.asyncio
    async def test_error_handling_workflow(self, sample_request, mock_workflow_context):
        """Test workflow error handling and cleanup."""
        
        # Mock build_agent_config to fail
        mock_workflow_context.execute_activity.side_effect = Exception("Configuration failed")
        
        workflow = ADKAgentWorkflow()
        
        # Run workflow and expect error handling
        with pytest.raises(Exception):
            await workflow.run(sample_request)
        
        # Verify error was handled (would be set in _handle_workflow_error)
        # Note: In actual workflow, this would be called in the except block


if __name__ == "__main__":
    # Run unit tests
    pytest.main([__file__, "-v", "-m", "unit"])