#!/usr/bin/env python3
"""
Unit tests for ADK Agent Workflow.

Tests the ADK-Temporal workflow integration to ensure proper functionality.
"""

import pytest
import asyncio
import logging
from unittest.mock import Mock, AsyncMock, patch
from uuid import uuid4, UUID
from datetime import timedelta

from temporalio.testing import WorkflowEnvironment
from temporalio.worker import Worker
from temporalio.common import RetryPolicy

# Import the workflow and models
from agentarea_execution.adk_temporal.workflows.adk_agent_workflow import ADKAgentWorkflow
from agentarea_execution.models import AgentExecutionRequest, AgentExecutionResult

# Configure logging for tests
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class TestADKAgentWorkflow:
    """Test suite for ADK Agent Workflow."""

    @pytest.fixture
    def sample_request(self):
        """Create a sample agent execution request."""
        return AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            user_id="test-user",
            task_query="Hello, can you help me with a test task?",
            timeout_seconds=60,
            max_reasoning_iterations=3
        )

    @pytest.fixture
    def sample_agent_config(self):
        """Create a sample agent configuration."""
        return {
            "id": str(uuid4()),
            "name": "test_agent",
            "description": "Test agent for unit testing",
            "model_id": "qwen2.5",
            "enable_streaming": False,
            "instructions": "You are a helpful test assistant."
        }

    @pytest.fixture
    def sample_events(self):
        """Create sample ADK events."""
        return [
            {
                "timestamp": 1234567890,
                "author": "assistant",
                "content": {
                    "parts": [
                        {"text": "Hello! I'm here to help you with your test task."}
                    ]
                },
                "cost": 0.001
            },
            {
                "timestamp": 1234567891,
                "author": "assistant", 
                "content": {
                    "parts": [
                        {"text": "How can I assist you today?"}
                    ]
                },
                "cost": 0.002
            }
        ]

    @pytest.mark.asyncio
    async def test_workflow_initialization(self, sample_request):
        """Test workflow initialization."""
        workflow = ADKAgentWorkflow()
        
        # Check initial state
        assert workflow.execution_id == ""
        assert workflow.agent_config == {}
        assert workflow.events == []
        assert workflow.final_response is None
        assert workflow.success is False
        assert workflow.paused is False
        assert workflow.start_time == 0.0
        assert workflow.end_time == 0.0

    @pytest.mark.asyncio
    async def test_extract_final_response(self, sample_events):
        """Test final response extraction from events."""
        workflow = ADKAgentWorkflow()
        
        # Test with valid events
        final_response = workflow._extract_final_response(sample_events)
        assert final_response == "How can I assist you today?"
        
        # Test with empty events
        assert workflow._extract_final_response([]) is None
        
        # Test with malformed events
        malformed_events = [{"invalid": "event"}]
        assert workflow._extract_final_response(malformed_events) is None

    @pytest.mark.asyncio
    async def test_calculate_total_cost(self, sample_events):
        """Test cost calculation from events."""
        workflow = ADKAgentWorkflow()
        
        total_cost = workflow._calculate_total_cost(sample_events)
        assert total_cost == 0.003  # 0.001 + 0.002
        
        # Test with events without cost
        events_no_cost = [{"content": {"parts": [{"text": "test"}]}}]
        assert workflow._calculate_total_cost(events_no_cost) == 0.0

    @pytest.mark.asyncio
    async def test_workflow_queries(self, sample_request, sample_agent_config, sample_events):
        """Test workflow query methods."""
        workflow = ADKAgentWorkflow()
        
        # Set up workflow state
        workflow.execution_id = "test-execution-id"
        workflow.agent_config = sample_agent_config
        workflow.events = sample_events
        workflow.final_response = "Test response"
        workflow.success = True
        workflow.paused = False
        
        # Test get_current_state
        state = workflow.get_current_state()
        assert state["execution_id"] == "test-execution-id"
        assert state["agent_name"] == "test_agent"
        assert state["event_count"] == 2
        assert state["success"] is True
        assert state["paused"] is False
        assert state["has_final_response"] is True
        
        # Test get_events
        events = workflow.get_events()
        assert len(events) == 2
        assert events == sample_events
        
        # Test get_events with limit
        limited_events = workflow.get_events(limit=1)
        assert len(limited_events) == 1
        assert limited_events[0] == sample_events[-1]  # Should get last event
        
        # Test get_final_response
        assert workflow.get_final_response() == "Test response"

    @pytest.mark.asyncio
    async def test_workflow_signals(self):
        """Test workflow signal methods."""
        workflow = ADKAgentWorkflow()
        
        # Test pause signal
        await workflow.pause("Test pause")
        assert workflow.paused is True
        assert workflow.pause_reason == "Test pause"
        
        # Test resume signal
        await workflow.resume("Test resume")
        assert workflow.paused is False
        assert workflow.pause_reason == ""

    @pytest.mark.asyncio
    async def test_should_use_streaming(self, sample_agent_config):
        """Test streaming mode detection."""
        workflow = ADKAgentWorkflow()
        
        # Test with streaming disabled
        workflow.agent_config = sample_agent_config
        assert workflow._should_use_streaming() is False
        
        # Test with streaming enabled
        workflow.agent_config = {**sample_agent_config, "enable_streaming": True}
        assert workflow._should_use_streaming() is True

    @pytest.mark.asyncio
    async def test_workflow_error_handling(self):
        """Test workflow error handling."""
        workflow = ADKAgentWorkflow()
        
        test_error = Exception("Test error")
        await workflow._handle_workflow_error(test_error)
        
        assert workflow.error_message == "Test error"
        assert workflow.success is False

    @pytest.mark.asyncio
    async def test_workflow_configuration_building(self, sample_request, sample_agent_config):
        """Test workflow configuration building logic."""
        workflow = ADKAgentWorkflow()
        
        # Test model ID processing
        workflow.agent_config = {"model_id": "qwen2.5"}
        workflow.session_data = {"state": {"agent_id": str(uuid4())}}
        workflow.user_message = {"content": "test message"}
        
        # Test batch execution preparation (without actual execution)
        model_id = workflow.agent_config.get("model_id", "qwen2.5")
        if "/" not in model_id:
            model_id = f"ollama_chat/{model_id}"
        
        adk_agent_config = {
            "name": f"agent_{str(workflow.session_data['state']['agent_id']).replace('-', '_')}",
            "model": model_id,
            "instructions": f"You are an AI assistant. Task: {workflow.user_message['content']}",
            "description": workflow.agent_config.get("description", "AgentArea task execution agent"),
            "tools": []
        }
        
        # Verify configuration structure
        assert adk_agent_config["name"].startswith("agent_")
        assert adk_agent_config["model"] == "ollama_chat/qwen2.5"
        assert "test message" in adk_agent_config["instructions"]
        assert adk_agent_config["tools"] == []

    def test_workflow_version(self):
        """Test workflow version is set correctly."""
        assert ADKAgentWorkflow.VERSION == "1.0.0"

    @pytest.mark.asyncio
    async def test_log_metrics(self, sample_events):
        """Test metrics logging."""
        workflow = ADKAgentWorkflow()
        workflow.execution_id = "test-execution"
        workflow.events = sample_events
        workflow.success = True
        workflow.total_cost = 0.003
        workflow.start_time = 1000.0
        workflow.end_time = 1005.0
        
        # This should not raise an exception
        workflow._log_metrics()

    @pytest.mark.asyncio
    async def test_finalize_execution_with_conversation_history(self, sample_events):
        """Test finalization with proper conversation history extraction."""
        workflow = ADKAgentWorkflow()
        workflow.events = sample_events
        workflow.success = True
        workflow.final_response = "Test response"
        workflow.session_data = {
            "state": {
                "task_id": str(uuid4()),
                "agent_id": str(uuid4())
            }
        }
        
        result_data = {"event_count": 2, "final_response": "Test response", "success": True}
        
        result = await workflow._finalize_execution(result_data)
        
        assert isinstance(result, AgentExecutionResult)
        assert result.success is True
        assert result.final_response == "Test response"
        assert len(result.conversation_history) == 2
        assert result.conversation_history[0]["content"] == "Hello! I'm here to help you with your test task."
        assert result.conversation_history[1]["content"] == "How can I assist you today?"


if __name__ == "__main__":
    # Run tests with pytest
    pytest.main([__file__, "-v"])