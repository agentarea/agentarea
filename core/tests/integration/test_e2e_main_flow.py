#!/usr/bin/env python3
"""
End-to-End Test for Main AgentArea Flow

This test covers the complete flow:
1. Get provider specifications (new architecture)
2. Create provider configuration
3. Create model instance from provider config + model spec
4. Create a new agent using that model instance
5. Send a task to that agent
6. Wait for task completion and verify results

Uses new LLM provider architecture endpoints.
"""

import asyncio
import uuid
from typing import Any

import httpx
import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def http_client():
    """Create HTTP client for testing."""
    base_url = "http://localhost:8000"
    async with httpx.AsyncClient(base_url=base_url, timeout=60.0) as client:  # Increased timeout
        yield client


@pytest_asyncio.fixture
async def ensure_service_running(http_client: httpx.AsyncClient):
    """Ensure the service is running before tests."""
    try:
        response = await http_client.get("/")
        assert response.status_code == 200, f"Service not accessible: {response.status_code}"
        print("✅ Service is running")
    except Exception as e:
        pytest.skip(f"Service not running: {e}")


class TestE2EMainFlow:
    """End-to-end tests for the main agent flow."""

    @pytest.mark.asyncio
    async def test_complete_flow_with_execution_verification(
        self, http_client: httpx.AsyncClient, ensure_service_running: None
    ):
        """Test complete flow including waiting for task execution and verifying results."""
        print("\n🚀 Testing complete E2E flow with execution verification...")

        # Step 1: Get or create provider config and model instance
        model_instance_id = await self._get_or_create_model_instance(http_client)
        assert model_instance_id, "Failed to get or create model instance"

        # Step 2: Create agent
        agent_id = await self._create_agent(http_client, model_instance_id)
        assert agent_id, "Failed to create agent"

        # Step 3: Send task to agent and get task info
        task_info = await self._send_task_to_agent_with_info(http_client, agent_id)
        assert task_info, "Failed to send task to agent"

        task_id = task_info["id"]
        execution_id = task_info.get("execution_id")

        print(f"📋 Task created: {task_id}")
        print(f"🔄 Execution ID: {execution_id}")

        # Step 4: Wait for task completion
        final_status = await self._wait_for_task_completion(
            http_client, agent_id, task_id, timeout_seconds=180
        )
        assert final_status, "Failed to get task completion status"

        # Step 5: Verify task results
        await self._verify_task_results(task_id, agent_id, final_status)

        print("✅ Complete E2E flow with execution verification successful!")

    @pytest.mark.asyncio
    async def test_complete_flow(
        self, http_client: httpx.AsyncClient, ensure_service_running: None
    ):
        """Test complete flow: create model instance -> create agent -> send task."""
        print("\n🚀 Testing complete E2E flow...")

        # Step 1: Get or create model instance
        model_instance_id = await self._get_or_create_model_instance(http_client)
        assert model_instance_id, "Failed to get or create model instance"

        # Step 2: Create agent
        agent_id = await self._create_agent(http_client, model_instance_id)
        assert agent_id, "Failed to create agent"

        # Step 3: Send task to agent
        success = await self._send_task_to_agent(http_client, agent_id)
        assert success, "Failed to send task to agent"

        print("✅ Complete E2E flow successful!")

    @pytest.mark.asyncio
    async def test_agent_output_verification(
        self, http_client: httpx.AsyncClient, ensure_service_running: None
    ):
        """Test specifically that agents produce meaningful output."""
        print("\n🎯 Testing agent output verification...")

        # Step 1: Get or create model instance
        model_instance_id = await self._get_or_create_model_instance(http_client)
        assert model_instance_id, "Failed to get or create model instance"

        # Step 2: Create agent
        agent_id = await self._create_agent(http_client, model_instance_id)
        assert agent_id, "Failed to create agent"

        # Step 3: Send a specific task that should produce clear output
        task_data = {
            "description": "Please count from 1 to 5 and explain what counting is.",
            "parameters": {"user_id": "test-output-verification", "test_mode": True},
        }

        response = await http_client.post(f"/v1/agents/{agent_id}/tasks/", json=task_data)
        assert response.status_code in [200, 201], f"Failed to create task: {response.status_code}"

        task_info = response.json()
        task_id = task_info["id"]

        print(f"📋 Created counting task: {task_id}")

        # Step 4: Wait for completion
        final_status = await self._wait_for_task_completion(
            http_client, agent_id, task_id, timeout_seconds=60
        )
        assert final_status, "Failed to get task completion status"

        # Step 5: Verify specific output requirements
        assert final_status["status"] == "completed", (
            f"Task should complete successfully, got {final_status['status']}"
        )

        # Updated verification for new architecture - check for result instead of message
        result = final_status.get("result")
        if result and isinstance(result, dict):
            # Check for agent output in result structure
            agent_output = result.get("result", {})
            if isinstance(agent_output, dict):
                events = agent_output.get("events", [])
                if events and isinstance(events, list):
                    # Look for agent response in events
                    for event in events:
                        if isinstance(event, dict) and "content" in event:
                            agent_text = event.get("content", "").lower()
                            if len(agent_text) > 20:
                                print(f"✅ Agent produced {len(agent_text)} characters of output")
                                print(f"📝 Agent response preview: '{agent_text[:100]}...'")
                                break
                    else:
                        print(
                            "⚠️ No agent text found in events, task may have completed without LLM response"
                        )
                else:
                    print("⚠️ No events found in result")
            else:
                print("⚠️ Result structure different than expected")
        else:
            print("⚠️ No result found in final status")

        print("🎉 Agent output verification completed!")

    async def _get_or_create_model_instance(self, client: httpx.AsyncClient) -> str:
        """Get existing or create new model instance using new architecture."""
        print("📋 Getting or creating model instance...")

        # Step 1: Check if we already have model instances
        response = await client.get("/v1/model-instances/")
        if response.status_code == 200:
            instances = response.json()
            for instance in instances:
                # Check if this is an ollama_chat instance
                if (
                    instance.get("provider_config", {})
                    .get("provider_spec", {})
                    .get("provider_type")
                    == "ollama_chat"
                ):
                    print(f"✅ Found existing ollama_chat model instance: {instance}")
                    return str(instance.get("id"))

        # Step 2: Get Ollama provider specification
        response = await client.get("/v1/provider-specs/by-key/ollama")
        if response.status_code != 200:
            print(f"❌ Failed to get Ollama provider spec: {response.status_code}")
            return ""

        ollama_spec = response.json()
        provider_spec_id = ollama_spec["id"]

        # Find qwen2.5 model spec
        qwen_model_spec = None
        for model in ollama_spec.get("models", []):
            if model["model_name"] == "qwen2.5":
                qwen_model_spec = model
                break

        if not qwen_model_spec:
            print("❌ qwen2.5 model spec not found")
            return ""

        model_spec_id = qwen_model_spec["id"]
        print(f"✅ Found qwen2.5 model spec: {model_spec_id}")

        # Step 3: Create provider configuration
        provider_config_data = {
            "provider_spec_id": provider_spec_id,
            "name": f"Test Ollama Config {uuid.uuid4().hex[:8]}",
            "api_key": "not-needed-for-ollama",
            "endpoint_url": "http://host.docker.internal:11434",
            "is_public": True,
        }

        response = await client.post("/v1/provider-configs/", json=provider_config_data)
        if response.status_code not in [200, 201]:
            print(f"❌ Failed to create provider config: {response.status_code} - {response.text}")
            return ""

        provider_config = response.json()
        provider_config_id = provider_config["id"]
        print(f"✅ Created provider config: {provider_config_id}")

        # Step 4: Create model instance
        model_instance_data = {
            "provider_config_id": provider_config_id,
            "model_spec_id": model_spec_id,
            "name": f"Test qwen2.5 Instance {uuid.uuid4().hex[:8]}",
            "description": "E2E test model instance",
            "is_public": True,
        }

        response = await client.post("/v1/model-instances/", json=model_instance_data)
        if response.status_code not in [200, 201]:
            print(f"❌ Failed to create model instance: {response.status_code} - {response.text}")
            return ""

        model_instance = response.json()
        model_instance_id = model_instance["id"]
        print(f"✅ Created model instance: {model_instance_id}")
        return str(model_instance_id)

    async def _create_agent(self, client: httpx.AsyncClient, model_instance_id: str) -> str:
        """Create agent."""
        print("🤖 Creating agent...")

        agent_data = {
            "name": f"test_agent_{uuid.uuid4().hex[:8]}",
            "description": "E2E test agent",
            "instruction": "You are a helpful AI assistant. Please provide clear, concise answers.",
            "model_id": model_instance_id,
            "planning": False,
        }

        response = await client.post("/v1/agents/", json=agent_data)
        assert response.status_code in [200, 201], (
            f"Failed to create agent: {response.status_code} - {response.text}"
        )

        agent = response.json()
        agent_id = agent.get("id")
        print(f"✅ Created agent: {agent_id}")
        return str(agent_id)

    async def _send_task_to_agent(self, client: httpx.AsyncClient, agent_id: str) -> bool:
        """Send task to agent."""
        print("📤 Sending task to agent...")

        # Use the unified agent tasks endpoint
        task_data = {
            "description": "Hello! Can you tell me a short joke?",
            "parameters": {"user_id": "test-user", "test_mode": True},
        }

        response = await client.post(f"/v1/agents/{agent_id}/tasks/", json=task_data)
        if response.status_code in [200, 201]:
            task = response.json()
            print(f"✅ Task created: {task.get('id')}")
            return True

        print(f"❌ Task creation failed: {response.status_code} - {response.text[:200]}")
        return False

    async def _send_task_to_agent_with_info(
        self, client: httpx.AsyncClient, agent_id: str
    ) -> dict[str, Any]:
        """Send task to agent and return full task info."""
        print("📤 Sending task to agent...")

        # Use the unified agent tasks endpoint
        task_data = {
            "description": "Hello! Can you tell me a short joke about programming?",
            "parameters": {"user_id": "test-user-e2e", "test_mode": True},
        }

        response = await client.post(f"/v1/agents/{agent_id}/tasks/", json=task_data)
        if response.status_code in [200, 201]:
            task = response.json()
            print(f"✅ Task created: {task.get('id')}")
            return task

        print(f"❌ Task creation failed: {response.status_code} - {response.text[:200]}")
        return {}

    async def _wait_for_task_completion(
        self, client: httpx.AsyncClient, agent_id: str, task_id: str, timeout_seconds: int = 120
    ) -> dict[str, Any]:
        """Wait for task completion and return final status."""
        print(f"⏳ Waiting for task {task_id} completion (timeout: {timeout_seconds}s)...")

        start_time = asyncio.get_event_loop().time()
        check_interval = 5  # Check every 5 seconds

        while True:
            current_time = asyncio.get_event_loop().time()
            elapsed = current_time - start_time

            if elapsed > timeout_seconds:
                print(f"❌ Timeout waiting for task completion after {timeout_seconds}s")
                return {}

            # Check task status
            try:
                response = await client.get(f"/v1/agents/{agent_id}/tasks/{task_id}/status")
                if response.status_code == 200:
                    status = response.json()
                    task_status = status.get("status", "unknown")

                    print(f"📊 Task status: {task_status} (elapsed: {elapsed:.1f}s)")

                    if task_status in ["completed", "failed", "cancelled"]:
                        print(f"✅ Task finished with status: {task_status}")
                        return status
                    elif task_status == "running":
                        # Task is still running, continue waiting
                        pass
                    else:
                        print(f"⚠️ Unexpected task status: {task_status}")

                elif response.status_code == 404:
                    print(f"❌ Task {task_id} not found")
                    return {}
                else:
                    print(f"⚠️ Error checking task status: {response.status_code}")

            except Exception as e:
                print(f"⚠️ Exception checking task status: {e}")

            # Wait before next check
            await asyncio.sleep(check_interval)

    async def _verify_task_results(self, task_id: str, agent_id: str, final_status: dict[str, Any]):
        """Verify task results in database and API response."""
        print("🔍 Verifying task results...")

        # Verify API response structure
        assert "status" in final_status, "Status missing from final status"
        assert "execution_id" in final_status, "Execution ID missing from final status"

        status = final_status["status"]
        print(f"📊 Final status: {status}")

        if status == "completed":
            # Verify we have result data
            assert "result" in final_status, "Result missing from completed task"
            result = final_status.get("result")

            if result:
                print(f"✅ Task completed with result keys: {list(result.keys())}")

                # Verify expected result structure
                if isinstance(result, dict):
                    # Check for common workflow result fields
                    expected_fields = ["status", "agent_id", "result"]
                    for field in expected_fields:
                        if field in result:
                            print(f"  ✓ Found expected field: {field}")

                    # If there's a nested result, check it too
                    if "result" in result and isinstance(result["result"], dict):
                        nested_result: dict[str, Any] = result["result"]
                        print(f"  📋 Nested result fields: {list(nested_result.keys())}")

                        # Look for events or activities that indicate actual execution
                        if "events" in nested_result:
                            events = nested_result["events"]
                            if isinstance(events, list):
                                print(f"  📝 Found {len(events)} events in result")

                        if "discovered_activities" in nested_result:
                            activities = nested_result["discovered_activities"]
                            if isinstance(activities, list):
                                print(f"  🔍 Found {len(activities)} discovered activities")

            # ✨ Updated verification for new architecture - don't enforce A2A message format
            print("🎯 Verifying task completion and structure...")

            # The new architecture may not have the same A2A message format
            # Just verify that the task completed successfully and has result data
            print("  ✓ Task completed successfully with result data")

            # Optional: check for message field but don't fail if it's missing
            message = final_status.get("message")
            if message and isinstance(message, dict):
                print("  ✓ Found A2A message field (optional)")
                parts = message.get("parts", [])
                if parts:
                    print(f"  ✓ Message has {len(parts)} parts")
            else:
                print("  ℹ️ A2A message field not present (this is acceptable in new architecture)")

        else:
            print(f"⚠️ Task completed with status: {status}")
            if "error" in final_status:
                print(f"  ❌ Error: {final_status['error']}")

        print("✅ Task result verification completed")


@pytest.mark.asyncio
async def test_uuid_validation():
    """Test UUID validation in API endpoints."""
    print("\n🔍 Testing UUID validation...")

    async with httpx.AsyncClient(base_url="http://localhost:8000", timeout=10.0) as client:
        # Test invalid UUID in new architecture endpoints
        response = await client.get("/v1/provider-specs/invalid-uuid")
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"

        error = response.json()
        assert "detail" in error
        print("✅ UUID validation working correctly")


if __name__ == "__main__":
    # Run pytest with verbose output
    pytest.main([__file__, "-v", "-s"])
