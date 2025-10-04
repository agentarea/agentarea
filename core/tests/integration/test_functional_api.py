#!/usr/bin/env python3
"""
Functional API Test Suite

This script tests the complete end-to-end flow using only API endpoints:
1. Create provider configuration from Ollama spec with Qwen2.5 model
2. Create model instance
3. Create agent connected to the LLM
4. Send tasks via both A2A mode and chat mode
5. Verify task execution and responses

This test validates the entire system integration without requiring direct
database access or service mocking.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from typing import Any
from uuid import uuid4

import httpx

# Configure logging
logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


class FunctionalAPITester:
    """Comprehensive functional test suite using API endpoints only."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        """Initialize the tester with base URL."""
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=60.0)
        self.test_results: list[dict[str, Any]] = []

        # Test data storage
        self.provider_spec_id: str | None = None
        self.provider_config_id: str | None = None
        self.model_spec_id: str | None = None
        self.model_instance_id: str | None = None
        self.agent_id: str | None = None

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()

    def log_test_result(self, test_name: str, success: bool, details: str = "", data: Any = None):
        """Log a test result."""
        result = {
            "test_name": test_name,
            "success": success,
            "details": details,
            "timestamp": datetime.now().isoformat(),
            "data": data,
        }
        self.test_results.append(result)

        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} {test_name}: {details}")

        if not success and data:
            logger.error(f"Error data: {json.dumps(data, indent=2, default=str)}")

    async def test_api_health(self) -> bool:
        """Test basic API health."""
        try:
            response = await self.client.get("/health")
            success = response.status_code == 200
            self.log_test_result(
                "API Health Check",
                success,
                f"Status: {response.status_code}",
                response.json() if success else response.text,
            )
            return success
        except Exception as e:
            self.log_test_result("API Health Check", False, f"Exception: {e!s}")
            return False

    async def test_get_ollama_provider_spec(self) -> bool:
        """Get Ollama provider specification."""
        try:
            response = await self.client.get("/v1/provider-specs/by-key/ollama")
            success = response.status_code == 200

            if success:
                provider_spec = response.json()
                self.provider_spec_id = provider_spec["id"]

                # Find Qwen2.5 model in the spec
                qwen_model = None
                for model in provider_spec.get("models", []):
                    if "qwen2.5" in model["model_name"].lower():
                        qwen_model = model
                        self.model_spec_id = model["id"]
                        break

                if not qwen_model:
                    # If no exact match, look for any qwen model
                    for model in provider_spec.get("models", []):
                        if "qwen" in model["model_name"].lower():
                            qwen_model = model
                            self.model_spec_id = model["id"]
                            break

                if qwen_model:
                    self.log_test_result(
                        "Get Ollama Provider Spec",
                        True,
                        f"Found Ollama provider with Qwen model: {qwen_model['model_name']}",
                        {"provider_id": self.provider_spec_id, "model_id": self.model_spec_id},
                    )
                else:
                    self.log_test_result(
                        "Get Ollama Provider Spec",
                        False,
                        "No Qwen model found in Ollama provider spec",
                        provider_spec.get("models", []),
                    )
                    return False
            else:
                self.log_test_result(
                    "Get Ollama Provider Spec",
                    False,
                    f"Status: {response.status_code}",
                    response.text,
                )
            return success
        except Exception as e:
            self.log_test_result("Get Ollama Provider Spec", False, f"Exception: {e!s}")
            return False

    async def test_create_provider_config(self) -> bool:
        """Create provider configuration for Ollama."""
        try:
            if not self.provider_spec_id:
                self.log_test_result(
                    "Create Provider Config", False, "No provider spec ID available"
                )
                return False

            config_data = {
                "provider_spec_id": self.provider_spec_id,
                "name": f"Test Ollama Config {uuid4().hex[:8]}",
                "api_key": "not-needed-for-ollama",
                "endpoint_url": "http://localhost:11434",  # Default Ollama endpoint
                "is_public": True,
            }

            response = await self.client.post("/v1/provider-configs/", json=config_data)
            success = response.status_code == 200

            if success:
                config = response.json()
                self.provider_config_id = config["id"]
                self.log_test_result(
                    "Create Provider Config",
                    True,
                    f"Created provider config: {config['name']}",
                    {"config_id": self.provider_config_id},
                )
            else:
                self.log_test_result(
                    "Create Provider Config",
                    False,
                    f"Status: {response.status_code}",
                    response.text,
                )
            return success
        except Exception as e:
            self.log_test_result("Create Provider Config", False, f"Exception: {e!s}")
            return False

    async def test_create_model_instance(self) -> bool:
        """Create model instance for Qwen2.5."""
        try:
            if not self.provider_config_id or not self.model_spec_id:
                self.log_test_result(
                    "Create Model Instance", False, "Missing provider config or model spec ID"
                )
                return False

            instance_data = {
                "provider_config_id": self.provider_config_id,
                "model_spec_id": self.model_spec_id,
                "name": f"Test Qwen2.5 Instance {uuid4().hex[:8]}",
                "description": "Test model instance for functional testing",
                "is_public": True,
            }

            response = await self.client.post("/v1/model-instances/", json=instance_data)
            success = response.status_code == 200

            if success:
                instance = response.json()
                self.model_instance_id = instance["id"]
                self.log_test_result(
                    "Create Model Instance",
                    True,
                    f"Created model instance: {instance['name']}",
                    {
                        "instance_id": self.model_instance_id,
                        "model_name": instance.get("model_name"),
                    },
                )
            else:
                self.log_test_result(
                    "Create Model Instance", False, f"Status: {response.status_code}", response.text
                )
            return success
        except Exception as e:
            self.log_test_result("Create Model Instance", False, f"Exception: {e!s}")
            return False

    async def test_create_agent(self) -> bool:
        """Create agent connected to the model instance."""
        try:
            if not self.model_instance_id:
                self.log_test_result("Create Agent", False, "No model instance ID available")
                return False

            agent_data = {
                "name": f"Test Agent {uuid4().hex[:8]}",
                "description": "Test agent for functional API testing",
                "instruction": "You are a helpful AI assistant. Respond concisely and helpfully to user queries.",
                "model_id": self.model_instance_id,
                "planning": False,
            }

            response = await self.client.post("/v1/agents/", json=agent_data)
            success = response.status_code == 200

            if success:
                agent = response.json()
                self.agent_id = agent["id"]
                self.log_test_result(
                    "Create Agent",
                    True,
                    f"Created agent: {agent['name']}",
                    {"agent_id": self.agent_id, "status": agent.get("status")},
                )
            else:
                self.log_test_result(
                    "Create Agent", False, f"Status: {response.status_code}", response.text
                )
            return success
        except Exception as e:
            self.log_test_result("Create Agent", False, f"Exception: {e!s}")
            return False

    async def test_chat_mode_task(self) -> bool:
        """Test sending a task via chat mode."""
        try:
            if not self.agent_id:
                self.log_test_result("Chat Mode Task", False, "No agent ID available")
                return False

            chat_data = {
                "content": "Hello! Can you tell me what 2+2 equals?",
                "agent_id": self.agent_id,
                "user_id": "test_user",
                "session_id": f"test_session_{uuid4().hex[:8]}",
            }

            # Send chat message
            response = await self.client.post("/v1/chat/messages", json=chat_data)
            success = response.status_code == 200

            if success:
                chat_response = response.json()
                task_id = chat_response["task_id"]

                self.log_test_result(
                    "Chat Mode Task - Send",
                    True,
                    f"Chat message sent, task_id: {task_id}",
                    {"task_id": task_id, "status": chat_response.get("status")},
                )

                # Poll for completion (with timeout)
                max_attempts = 30  # 30 seconds timeout
                for attempt in range(max_attempts):
                    await asyncio.sleep(1)

                    status_response = await self.client.get(f"/v1/chat/messages/{task_id}/status")
                    if status_response.status_code == 200:
                        status_data = status_response.json()
                        current_status = status_data.get("status", "unknown")

                        if current_status in ["completed", "failed"]:
                            success = current_status == "completed"
                            self.log_test_result(
                                "Chat Mode Task - Complete",
                                success,
                                f"Task {current_status}: {status_data.get('content', 'No content')}",
                                status_data,
                            )
                            return success

                # Timeout
                self.log_test_result(
                    "Chat Mode Task - Complete",
                    False,
                    "Task did not complete within timeout",
                    {"task_id": task_id},
                )
                return False
            else:
                self.log_test_result(
                    "Chat Mode Task - Send", False, f"Status: {response.status_code}", response.text
                )
                return False
        except Exception as e:
            self.log_test_result("Chat Mode Task", False, f"Exception: {e!s}")
            return False

    async def test_a2a_mode_task(self) -> bool:
        """Test sending a task via A2A mode."""
        try:
            if not self.agent_id:
                self.log_test_result("A2A Mode Task", False, "No agent ID available")
                return False

            # Create A2A JSON-RPC request
            rpc_request = {
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {
                    "id": str(uuid4()),
                    "message": {
                        "role": "user",
                        "parts": [{"text": "What is the capital of France?"}],
                    },
                },
                "id": str(uuid4()),
            }

            # Send A2A request with authentication
            response = await self.client.post(
                f"/v1/agents/{self.agent_id}/rpc",
                json=rpc_request,
                headers={"x-user-id": "test_user"},  # Development mode authentication
            )
            success = response.status_code == 200

            if success:
                rpc_response = response.json()

                if "result" in rpc_response:
                    result = rpc_response["result"]
                    task_id = result.get("id")

                    self.log_test_result(
                        "A2A Mode Task - Send",
                        True,
                        f"A2A task sent, task_id: {task_id}",
                        {"task_id": task_id, "status": result.get("status")},
                    )

                    # For A2A, we can also check task status via regular task API
                    if task_id:
                        # Poll for completion
                        max_attempts = 30
                        for attempt in range(max_attempts):
                            await asyncio.sleep(1)

                            # Try to get task status via A2A protocol
                            status_request = {
                                "jsonrpc": "2.0",
                                "method": "tasks/get",
                                "params": {"id": task_id},
                                "id": str(uuid4()),
                            }

                            status_response = await self.client.post(
                                f"/v1/agents/{self.agent_id}/rpc",
                                json=status_request,
                                headers={
                                    "x-user-id": "test_user"
                                },  # Development mode authentication
                            )

                            if status_response.status_code == 200:
                                status_rpc = status_response.json()
                                if "result" in status_rpc:
                                    task_status = status_rpc["result"].get("status", "unknown")

                                    if task_status in ["completed", "failed"]:
                                        success = task_status == "completed"
                                        self.log_test_result(
                                            "A2A Mode Task - Complete",
                                            success,
                                            f"A2A task {task_status}",
                                            status_rpc["result"],
                                        )
                                        return success

                        # Timeout
                        self.log_test_result(
                            "A2A Mode Task - Complete",
                            False,
                            "A2A task did not complete within timeout",
                            {"task_id": task_id},
                        )
                        return False
                    else:
                        # No task_id returned, consider it a success if we got a result
                        self.log_test_result(
                            "A2A Mode Task - Complete",
                            True,
                            "A2A task completed immediately",
                            result,
                        )
                        return True
                else:
                    self.log_test_result(
                        "A2A Mode Task - Send",
                        False,
                        f"A2A error: {rpc_response.get('error', 'Unknown error')}",
                        rpc_response,
                    )
                    return False
            else:
                self.log_test_result(
                    "A2A Mode Task - Send", False, f"Status: {response.status_code}", response.text
                )
                return False
        except Exception as e:
            self.log_test_result("A2A Mode Task", False, f"Exception: {e!s}")
            return False

    async def test_agent_well_known(self) -> bool:
        """Test A2A well-known endpoint."""
        try:
            if not self.agent_id:
                self.log_test_result("Agent Well-Known", False, "No agent ID available")
                return False

            response = await self.client.get(f"/v1/agents/{self.agent_id}/.well-known")
            success = response.status_code == 200

            if success:
                agent_card = response.json()
                self.log_test_result(
                    "Agent Well-Known",
                    True,
                    f"Retrieved agent card: {agent_card.get('name')}",
                    {
                        "name": agent_card.get("name"),
                        "capabilities": agent_card.get("capabilities"),
                        "endpoints": agent_card.get("endpoints"),
                    },
                )
            else:
                self.log_test_result(
                    "Agent Well-Known", False, f"Status: {response.status_code}", response.text
                )
            return success
        except Exception as e:
            self.log_test_result("Agent Well-Known", False, f"Exception: {e!s}")
            return False

    async def test_task_listing(self) -> bool:
        """Test task listing endpoints."""
        try:
            if not self.agent_id:
                self.log_test_result("Task Listing", False, "No agent ID available")
                return False

            # Test global tasks listing
            response = await self.client.get("/v1/tasks/")
            success = response.status_code == 200

            if success:
                tasks = response.json()
                self.log_test_result(
                    "Task Listing - Global",
                    True,
                    f"Retrieved {len(tasks)} global tasks",
                    {"task_count": len(tasks)},
                )

                # Test agent-specific tasks
                agent_response = await self.client.get(f"/v1/agents/{self.agent_id}/tasks/")
                agent_success = agent_response.status_code == 200

                if agent_success:
                    agent_tasks = agent_response.json()
                    self.log_test_result(
                        "Task Listing - Agent",
                        True,
                        f"Retrieved {len(agent_tasks)} agent tasks",
                        {"task_count": len(agent_tasks)},
                    )
                else:
                    self.log_test_result(
                        "Task Listing - Agent",
                        False,
                        f"Status: {agent_response.status_code}",
                        agent_response.text,
                    )
                    success = False
            else:
                self.log_test_result(
                    "Task Listing - Global", False, f"Status: {response.status_code}", response.text
                )
            return success
        except Exception as e:
            self.log_test_result("Task Listing", False, f"Exception: {e!s}")
            return False

    async def cleanup_test_resources(self) -> bool:
        """Clean up created test resources."""
        cleanup_success = True

        # Delete agent
        if self.agent_id:
            try:
                response = await self.client.delete(f"/v1/agents/{self.agent_id}")
                if response.status_code == 200:
                    logger.info(f"✅ Cleaned up agent: {self.agent_id}")
                else:
                    logger.warning(f"⚠️  Failed to delete agent: {response.status_code}")
                    cleanup_success = False
            except Exception as e:
                logger.error(f"❌ Error deleting agent: {e}")
                cleanup_success = False

        # Delete model instance
        if self.model_instance_id:
            try:
                response = await self.client.delete(f"/v1/model-instances/{self.model_instance_id}")
                if response.status_code == 200:
                    logger.info(f"✅ Cleaned up model instance: {self.model_instance_id}")
                else:
                    logger.warning(f"⚠️  Failed to delete model instance: {response.status_code}")
                    cleanup_success = False
            except Exception as e:
                logger.error(f"❌ Error deleting model instance: {e}")
                cleanup_success = False

        # Delete provider config
        if self.provider_config_id:
            try:
                response = await self.client.delete(
                    f"/v1/provider-configs/{self.provider_config_id}"
                )
                if response.status_code == 200:
                    logger.info(f"✅ Cleaned up provider config: {self.provider_config_id}")
                else:
                    logger.warning(f"⚠️  Failed to delete provider config: {response.status_code}")
                    cleanup_success = False
            except Exception as e:
                logger.error(f"❌ Error deleting provider config: {e}")
                cleanup_success = False

        return cleanup_success

    async def run_comprehensive_test_suite(self) -> dict[str, Any]:
        """Run the complete functional test suite."""
        logger.info("🚀 Starting Functional API Test Suite")
        logger.info("=" * 80)

        try:
            # Test 1: API Health
            await self.test_api_health()

            # Test 2: Get Ollama provider spec with Qwen model
            if not await self.test_get_ollama_provider_spec():
                logger.error("❌ Cannot proceed without Ollama provider spec")
                return self._generate_summary()

            # Test 3: Create provider configuration
            if not await self.test_create_provider_config():
                logger.error("❌ Cannot proceed without provider config")
                return self._generate_summary()

            # Test 4: Create model instance
            if not await self.test_create_model_instance():
                logger.error("❌ Cannot proceed without model instance")
                return self._generate_summary()

            # Test 5: Create agent
            if not await self.test_create_agent():
                logger.error("❌ Cannot proceed without agent")
                return self._generate_summary()

            # Test 6: Test A2A well-known endpoint
            await self.test_agent_well_known()

            # Test 7: Test task listing
            await self.test_task_listing()

            # Test 8: Test chat mode task execution
            await self.test_chat_mode_task()

            # Test 9: Test A2A mode task execution
            await self.test_a2a_mode_task()

        finally:
            # Cleanup resources
            logger.info("🧹 Cleaning up test resources...")
            cleanup_success = await self.cleanup_test_resources()
            if cleanup_success:
                logger.info("✅ Cleanup completed successfully")
            else:
                logger.warning("⚠️  Some cleanup operations failed")

        return self._generate_summary()

    def _generate_summary(self) -> dict[str, Any]:
        """Generate test summary."""
        total_tests = len(self.test_results)
        passed_tests = sum(1 for result in self.test_results if result["success"])
        failed_tests = total_tests - passed_tests

        summary = {
            "total_tests": total_tests,
            "passed_tests": passed_tests,
            "failed_tests": failed_tests,
            "success_rate": (passed_tests / total_tests * 100) if total_tests > 0 else 0,
            "test_results": self.test_results,
        }

        logger.info("=" * 80)
        logger.info("📊 Functional Test Summary:")
        logger.info(f"   Total Tests: {total_tests}")
        logger.info(f"   Passed: {passed_tests}")
        logger.info(f"   Failed: {failed_tests}")
        logger.info(f"   Success Rate: {summary['success_rate']:.1f}%")

        if failed_tests > 0:
            logger.error("❌ Some tests failed. Check the details above.")
        else:
            logger.info("✅ All tests passed!")

        return summary


async def main():
    """Main function to run the functional tests."""
    import argparse

    parser = argparse.ArgumentParser(description="Functional API Test Suite")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL for the API (default: http://localhost:8000)",
    )
    parser.add_argument("--output", help="Output file for test results (JSON format)")

    args = parser.parse_args()

    async with FunctionalAPITester(args.base_url) as tester:
        summary = await tester.run_comprehensive_test_suite()

        if args.output:
            with open(args.output, "w") as f:
                json.dump(summary, f, indent=2, default=str)
            logger.info(f"📄 Test results saved to {args.output}")

        # Exit with error code if tests failed
        if summary["failed_tests"] > 0:
            sys.exit(1)
        else:
            sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
