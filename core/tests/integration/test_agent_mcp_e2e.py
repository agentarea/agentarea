"""
E2E test for Agent + MCP integration.

This test verifies the complete flow:
1. Create an MCP server, assign it to an agent, and execute a task that uses the MCP tool
2. Verify MCP tool calls are executed and stored correctly
"""

import json
import logging
import time
from typing import Any, Dict, List, Optional

import pytest
import requests

logger = logging.getLogger(__name__)

# Test configuration
API_BASE_URL = "http://localhost:8000"


class TestAgentMCPE2E:
    """End-to-end test for Agent + MCP integration."""

    def setup_method(self):
        """Set up test environment."""
        self.mcp_server_id = None
        self.mcp_instance_id = None
        self.agent_id = None
        self.task_id = None

    def teardown_method(self):
        """Clean up test resources."""
        # Clean up in reverse order
        if self.task_id:
            requests.delete(f"{API_BASE_URL}/tasks/{self.task_id}")
        if self.agent_id:
            requests.delete(f"{API_BASE_URL}/agents/{self.agent_id}")
        if self.mcp_instance_id:
            requests.delete(f"{API_BASE_URL}/mcp/instances/{self.mcp_instance_id}")
        if self.mcp_server_id:
            requests.delete(f"{API_BASE_URL}/mcp/servers/{self.mcp_server_id}")

    def create_echo_mcp_server(self) -> Dict[str, Any]:
        """Create an echo MCP server for testing."""
        server_data = {
            "name": "echo-mcp-server",
            "description": "Echo MCP server for testing agent integration",
            "docker_image": "mcp-echo-server:latest",
            "ports": [{"port": 3000, "protocol": "http"}],
            "tools": [
                {
                    "name": "echo",
                    "description": "Echo back the input text",
                    "input_schema": {
                        "type": "object",
                        "properties": {
                            "text": {
                                "type": "string",
                                "description": "Text to echo back"
                            }
                        },
                        "required": ["text"]
                    }
                }
            ],
            "endpoint_schema": {
                "base_url": "http://localhost:3000",
                "health_check": "/health"
            }
        }

        response = requests.post(f"{API_BASE_URL}/mcp/servers", json=server_data)
        assert response.status_code == 201
        server = response.json()
        self.mcp_server_id = server["id"]
        return server

    def create_mcp_instance(self, server_id: str) -> Dict[str, Any]:
        """Create and deploy an MCP instance."""
        instance_data = {
            "name": "echo-mcp-instance",
            "server_spec_id": server_id,
            "json_spec": {
                "type": "docker",
                "image": "mcp-echo-server:latest",
                "port": 3000,
                "endpoint_url": "http://localhost:3000",
                "environment": {"PORT": "3000"},
                "resources": {"memory_limit": "256m", "cpu_limit": "0.5"}
            },
        }

        response = requests.post(f"{API_BASE_URL}/mcp/instances", json=instance_data)
        assert response.status_code == 201
        instance = response.json()
        self.mcp_instance_id = instance["id"]

        # Wait for deployment
        self._wait_for_instance_ready(instance["id"])
        return instance

    def create_agent_with_mcp(self, mcp_instance_id: str) -> Dict[str, Any]:
        """Create an agent with MCP server assigned."""
        agent_data = {
            "name": "mcp-test-agent",
            "description": "Agent for testing MCP integration",
            "model_id": "qwen2.5:latest",
            "instructions": "You are a helpful assistant that can use MCP tools. When asked to echo something, use the echo tool.",
            "mcp_server_ids": [mcp_instance_id],
            "capabilities": ["mcp_tools"]
        }

        response = requests.post(f"{API_BASE_URL}/agents", json=agent_data)
        assert response.status_code == 201
        agent = response.json()
        self.agent_id = agent["id"]
        return agent

    def execute_task_with_mcp(self, agent_id: str) -> Dict[str, Any]:
        """Execute a task that should use MCP tools."""
        task_data = {
            "agent_id": agent_id,
            "message": "Please echo the text 'Hello from MCP integration test!'",
            "priority": "high"
        }

        response = requests.post(f"{API_BASE_URL}/tasks", json=task_data)
        assert response.status_code == 201
        task = response.json()
        self.task_id = task["id"]

        # Wait for task completion
        self._wait_for_task_completion(task["id"])
        return self._get_task_details(task["id"])

    def _wait_for_instance_ready(self, instance_id: str, timeout: int = 60):
        """Wait for MCP instance to be ready."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = requests.get(f"{API_BASE_URL}/mcp/instances/{instance_id}")
            if response.status_code == 200:
                instance = response.json()
                if instance.get("status") == "running":
                    return
            time.sleep(2)
        
        raise TimeoutError(f"MCP instance {instance_id} did not become ready within {timeout}s")

    def _wait_for_task_completion(self, task_id: str, timeout: int = 120):
        """Wait for task to complete."""
        start_time = time.time()
        while time.time() - start_time < timeout:
            response = requests.get(f"{API_BASE_URL}/tasks/{task_id}")
            if response.status_code == 200:
                task = response.json()
                if task.get("status") in ["completed", "failed"]:
                    return
            time.sleep(3)
        
        raise TimeoutError(f"Task {task_id} did not complete within {timeout}s")

    def _get_task_details(self, task_id: str) -> Dict:
        """Get detailed task information."""
        response = requests.get(f"{API_BASE_URL}/tasks/{task_id}")
        assert response.status_code == 200
        return response.json()

    def verify_mcp_tool_calls_in_db(self, task_id: str):
        """Verify MCP tool calls are stored correctly in the database."""
        # Check database for tool call records
        with Session(get_db()) as db:
            # Get task from database
            task_stmt = select(AgentTask).where(AgentTask.id == task_id)
            task = db.execute(task_stmt).scalar_one_or_none()
            
            assert task is not None, f"Task {task_id} not found in database"
            
            # Check if task has tool call information
            # This might be stored in task metadata, temporal events, or separate tool_calls table
            # We'll check multiple possible locations
            
            tool_calls_found = False
            
            # Check task metadata for tool calls
            if task.metadata:
                metadata = json.loads(task.metadata) if isinstance(task.metadata, str) else task.metadata
                if "tool_calls" in metadata:
                    tool_calls = metadata["tool_calls"]
                    for call in tool_calls:
                        if call.get("name") == "echo" and "Hello from MCP integration test!" in str(call):
                            tool_calls_found = True
                            break
            
            # If we have a separate tool_calls table, check it here
            # This would depend on your implementation
            
            assert tool_calls_found, "MCP tool calls not found in database"

    def test_complete_agent_mcp_integration(self):
        """Test complete Agent + MCP integration flow."""
        logger.info("Starting Agent + MCP E2E integration test")

        # Step 1: Create MCP server
        logger.info("Creating MCP server...")
        mcp_server = self.create_echo_mcp_server()
        assert mcp_server["name"] == "echo-mcp-server"
        assert "echo" in [tool["name"] for tool in mcp_server["tools"]]

        # Step 2: Create and deploy MCP instance
        logger.info("Creating MCP instance...")
        mcp_instance = self.create_mcp_instance(mcp_server["id"])
        assert mcp_instance["server_spec_id"] == mcp_server["id"]

        # Step 3: Create agent with MCP assigned
        logger.info("Creating agent with MCP...")
        agent = self.create_agent_with_mcp(mcp_instance["id"])
        assert mcp_instance["id"] in agent["mcp_server_ids"]

        # Step 4: Execute task that uses MCP tools
        logger.info("Executing task with MCP tools...")
        task = self.execute_task_with_mcp(agent["id"])
        
        # Verify task completed successfully
        assert task["status"] == "completed", f"Task failed with status: {task['status']}"
        assert task["response"] is not None, "Task response is None"
        
        # Verify the echo was performed (response should contain echoed text)
        response_text = task["response"].lower()
        assert "hello from mcp integration test" in response_text, \
            f"Expected echo text not found in response: {task['response']}"

        # Step 5: Verify MCP tool calls are stored in database
        logger.info("Verifying MCP tool calls in database...")
        self.verify_mcp_tool_calls_in_db(task["id"])

        # Step 6: Verify agent-to-agent messages are populated
        assert "a2a_messages" in task, "A2A messages field missing"
        if task["a2a_messages"]:
            # Check that tool calls are recorded in A2A messages
            found_tool_call = False
            for message in task["a2a_messages"]:
                if message.get("type") == "tool_call" and message.get("tool_name") == "echo":
                    found_tool_call = True
                    break
            assert found_tool_call, "Tool call not found in A2A messages"

        logger.info("Agent + MCP E2E integration test completed successfully!")

    def test_agent_mcp_error_handling(self):
        """Test error handling when MCP server is unavailable."""
        logger.info("Testing Agent + MCP error handling")

        # Create MCP server but don't deploy instance
        mcp_server = self.create_echo_mcp_server()
        
        # Create agent with non-existent MCP instance
        fake_instance_id = "fake-instance-id"
        agent_data = {
            "name": "mcp-error-test-agent",
            "description": "Agent for testing MCP error handling",
            "model_id": "qwen2.5:latest",
            "instructions": "You are a helpful assistant.",
            "mcp_server_ids": [fake_instance_id],
            "capabilities": ["mcp_tools"]
        }

        # This should either fail during agent creation or handle gracefully during execution
        response = requests.post(f"{API_BASE_URL}/agents", json=agent_data)
        
        if response.status_code == 201:
            # Agent created successfully, test task execution with broken MCP
            agent = response.json()
            self.agent_id = agent["id"]
            
            task_data = {
                "agent_id": agent["id"],
                "message": "Please echo something",
                "priority": "high"
            }
            
            task_response = requests.post(f"{API_BASE_URL}/tasks", json=task_data)
            assert task_response.status_code == 201
            task = task_response.json()
            self.task_id = task["id"]
            
            # Wait for task completion (should handle MCP error gracefully)
            self._wait_for_task_completion(task["id"])
            final_task = self._get_task_details(task["id"])
            
            # Task should complete but may have an error message
            assert final_task["status"] in ["completed", "failed"]
            if final_task["status"] == "failed":
                assert "mcp" in final_task.get("error_message", "").lower()
        else:
            # Agent creation failed, which is also acceptable
            assert response.status_code == 422  # Validation error
            error_detail = response.json()
            assert "mcp" in str(error_detail).lower()

        logger.info("Agent + MCP error handling test completed!") 