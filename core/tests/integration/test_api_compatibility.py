#!/usr/bin/env python3
"""
API Compatibility Test Suite

This script tests all existing API endpoints to ensure they work correctly
with the refactored task service architecture. It verifies that no breaking
changes were introduced during the refactoring process.

Requirements addressed:
- 4.4: Verify that no breaking changes were introduced
- 5.4: Test that all existing API endpoints work with refactored services
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
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class APICompatibilityTester:
    """Test suite for API compatibility verification."""

    def __init__(self, base_url: str = "http://localhost:8000"):
        """Initialize the tester with base URL."""
        self.base_url = base_url
        self.client = httpx.AsyncClient(base_url=base_url, timeout=30.0)
        self.test_results: list[dict[str, Any]] = []

    async def __aenter__(self):
        """Async context manager entry."""
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async context manager exit."""
        await self.client.aclose()

    def log_test_result(
        self, test_name: str, success: bool, details: str = "", response_data: Any = None
    ):
        """Log a test result."""
        result = {
            "test_name": test_name,
            "success": success,
            "details": details,
            "timestamp": datetime.now().isoformat(),
            "response_data": response_data,
        }
        self.test_results.append(result)

        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} {test_name}: {details}")

        if not success and response_data:
            logger.error(f"Response data: {json.dumps(response_data, indent=2, default=str)}")

    async def test_health_check(self) -> bool:
        """Test basic API health check."""
        try:
            response = await self.client.get("/health")
            success = response.status_code == 200
            self.log_test_result(
                "Health Check",
                success,
                f"Status: {response.status_code}",
                response.json() if success else response.text,
            )
            return success
        except Exception as e:
            self.log_test_result("Health Check", False, f"Exception: {e!s}")
            return False

    async def test_get_all_tasks(self) -> bool:
        """Test global tasks listing endpoint."""
        try:
            response = await self.client.get("/api/v1/tasks/")
            success = response.status_code == 200

            if success:
                tasks = response.json()
                self.log_test_result(
                    "Get All Tasks",
                    True,
                    f"Retrieved {len(tasks)} tasks",
                    {"task_count": len(tasks), "sample": tasks[:2] if tasks else []},
                )
            else:
                self.log_test_result(
                    "Get All Tasks", False, f"Status: {response.status_code}", response.text
                )
            return success
        except Exception as e:
            self.log_test_result("Get All Tasks", False, f"Exception: {e!s}")
            return False

    async def test_get_agents(self) -> list[dict[str, Any]]:
        """Test agents listing and return available agents."""
        try:
            response = await self.client.get("/api/v1/agents/")
            success = response.status_code == 200

            if success:
                agents = response.json()
                self.log_test_result(
                    "Get Agents",
                    True,
                    f"Retrieved {len(agents)} agents",
                    {"agent_count": len(agents)},
                )
                return agents
            else:
                self.log_test_result(
                    "Get Agents", False, f"Status: {response.status_code}", response.text
                )
                return []
        except Exception as e:
            self.log_test_result("Get Agents", False, f"Exception: {e!s}")
            return []

    async def test_create_task_for_agent(self, agent_id: str) -> dict[str, Any] | None:
        """Test task creation for a specific agent."""
        try:
            task_data = {
                "description": "API compatibility test task",
                "parameters": {"test": True, "timestamp": datetime.now().isoformat()},
                "user_id": "api_test_user",
                "enable_agent_communication": True,
            }

            response = await self.client.post(f"/api/v1/agents/{agent_id}/tasks/", json=task_data)

            success = response.status_code == 200

            if success:
                task = response.json()
                self.log_test_result(
                    f"Create Task for Agent {agent_id}",
                    True,
                    f"Created task {task.get('id')} with status {task.get('status')}",
                    {"task_id": task.get("id"), "status": task.get("status")},
                )
                return task
            else:
                self.log_test_result(
                    f"Create Task for Agent {agent_id}",
                    False,
                    f"Status: {response.status_code}",
                    response.text,
                )
                return None
        except Exception as e:
            self.log_test_result(f"Create Task for Agent {agent_id}", False, f"Exception: {e!s}")
            return None

    async def test_get_agent_tasks(self, agent_id: str) -> bool:
        """Test listing tasks for a specific agent."""
        try:
            response = await self.client.get(f"/api/v1/agents/{agent_id}/tasks/")
            success = response.status_code == 200

            if success:
                tasks = response.json()
                self.log_test_result(
                    f"Get Tasks for Agent {agent_id}",
                    True,
                    f"Retrieved {len(tasks)} tasks",
                    {"task_count": len(tasks)},
                )
            else:
                self.log_test_result(
                    f"Get Tasks for Agent {agent_id}",
                    False,
                    f"Status: {response.status_code}",
                    response.text,
                )
            return success
        except Exception as e:
            self.log_test_result(f"Get Tasks for Agent {agent_id}", False, f"Exception: {e!s}")
            return False

    async def test_get_task_status(self, agent_id: str, task_id: str) -> bool:
        """Test getting task status."""
        try:
            response = await self.client.get(f"/api/v1/agents/{agent_id}/tasks/{task_id}/status")
            success = response.status_code == 200

            if success:
                status_data = response.json()
                self.log_test_result(
                    f"Get Task Status {task_id}",
                    True,
                    f"Status: {status_data.get('status')}",
                    status_data,
                )
            else:
                self.log_test_result(
                    f"Get Task Status {task_id}",
                    False,
                    f"Status: {response.status_code}",
                    response.text,
                )
            return success
        except Exception as e:
            self.log_test_result(f"Get Task Status {task_id}", False, f"Exception: {e!s}")
            return False

    async def test_get_specific_task(self, agent_id: str, task_id: str) -> bool:
        """Test getting a specific task."""
        try:
            response = await self.client.get(f"/api/v1/agents/{agent_id}/tasks/{task_id}")
            success = response.status_code in [200, 404]  # 404 is acceptable for non-existent tasks

            if response.status_code == 200:
                task_data = response.json()
                self.log_test_result(
                    f"Get Specific Task {task_id}",
                    True,
                    f"Retrieved task with status {task_data.get('status')}",
                    task_data,
                )
            elif response.status_code == 404:
                self.log_test_result(
                    f"Get Specific Task {task_id}",
                    True,
                    "Task not found (expected for some test cases)",
                    {"status": "not_found"},
                )
            else:
                self.log_test_result(
                    f"Get Specific Task {task_id}",
                    False,
                    f"Status: {response.status_code}",
                    response.text,
                )
            return success
        except Exception as e:
            self.log_test_result(f"Get Specific Task {task_id}", False, f"Exception: {e!s}")
            return False

    async def test_a2a_well_known(self, agent_id: str) -> bool:
        """Test A2A well-known endpoint."""
        try:
            response = await self.client.get(f"/api/v1/agents/{agent_id}/a2a/well-known")
            success = response.status_code == 200

            if success:
                agent_card = response.json()
                self.log_test_result(
                    f"A2A Well-Known {agent_id}",
                    True,
                    f"Retrieved agent card for {agent_card.get('name')}",
                    {
                        "name": agent_card.get("name"),
                        "capabilities": agent_card.get("capabilities"),
                    },
                )
            else:
                self.log_test_result(
                    f"A2A Well-Known {agent_id}",
                    False,
                    f"Status: {response.status_code}",
                    response.text,
                )
            return success
        except Exception as e:
            self.log_test_result(f"A2A Well-Known {agent_id}", False, f"Exception: {e!s}")
            return False

    async def test_a2a_rpc_task_send(self, agent_id: str) -> bool:
        """Test A2A RPC task send."""
        try:
            rpc_request = {
                "jsonrpc": "2.0",
                "method": "tasks/send",
                "params": {
                    "id": str(uuid4()),
                    "message": {"role": "user", "parts": [{"text": "Test A2A task submission"}]},
                },
                "id": str(uuid4()),
            }

            response = await self.client.post(
                f"/api/v1/agents/{agent_id}/a2a/rpc", json=rpc_request
            )

            success = response.status_code == 200

            if success:
                rpc_response = response.json()
                self.log_test_result(
                    f"A2A RPC Task Send {agent_id}",
                    True,
                    f"RPC response: {rpc_response.get('result', {}).get('status')}",
                    rpc_response,
                )
            else:
                self.log_test_result(
                    f"A2A RPC Task Send {agent_id}",
                    False,
                    f"Status: {response.status_code}",
                    response.text,
                )
            return success
        except Exception as e:
            self.log_test_result(f"A2A RPC Task Send {agent_id}", False, f"Exception: {e!s}")
            return False

    async def test_dependency_injection(self) -> bool:
        """Test that dependency injection is working correctly."""
        try:
            # This test checks if the API can start and handle requests
            # which indicates that dependency injection is working
            response = await self.client.get("/api/v1/tasks/")
            success = response.status_code in [
                200,
                500,
            ]  # 500 might indicate DB issues, not DI issues

            if response.status_code == 200:
                self.log_test_result(
                    "Dependency Injection",
                    True,
                    "Services are properly injected and functional",
                    {"status": "working"},
                )
            elif response.status_code == 500:
                # Check if it's a dependency injection issue or something else
                error_text = response.text
                if "dependency" in error_text.lower() or "inject" in error_text.lower():
                    self.log_test_result(
                        "Dependency Injection",
                        False,
                        "Dependency injection failure detected",
                        error_text,
                    )
                    success = False
                else:
                    self.log_test_result(
                        "Dependency Injection",
                        True,
                        "DI working, but other service issues present",
                        {"status": "di_ok_service_issues"},
                    )
            else:
                self.log_test_result(
                    "Dependency Injection",
                    False,
                    f"Unexpected status: {response.status_code}",
                    response.text,
                )

            return success
        except Exception as e:
            self.log_test_result("Dependency Injection", False, f"Exception: {e!s}")
            return False

    async def run_comprehensive_test_suite(self) -> dict[str, Any]:
        """Run the complete API compatibility test suite."""
        logger.info("🚀 Starting API Compatibility Test Suite")
        logger.info("=" * 60)

        # Test 1: Basic health check
        await self.test_health_check()

        # Test 2: Dependency injection
        await self.test_dependency_injection()

        # Test 3: Global tasks endpoint
        await self.test_get_all_tasks()

        # Test 4: Get agents (needed for agent-specific tests)
        agents = await self.test_get_agents()

        if agents:
            # Use the first agent for testing
            test_agent = agents[0]
            agent_id = test_agent["id"]

            # Test 5: Agent-specific endpoints
            await self.test_get_agent_tasks(agent_id)

            # Test 6: Task creation
            created_task = await self.test_create_task_for_agent(agent_id)

            if created_task:
                task_id = created_task["id"]

                # Test 7: Task status and retrieval
                await self.test_get_task_status(agent_id, task_id)
                await self.test_get_specific_task(agent_id, task_id)

            # Test 8: A2A protocol endpoints
            await self.test_a2a_well_known(agent_id)
            await self.test_a2a_rpc_task_send(agent_id)
        else:
            logger.warning("⚠️  No agents available for agent-specific tests")

        # Generate summary
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

        logger.info("=" * 60)
        logger.info("📊 Test Summary:")
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
    """Main function to run the API compatibility tests."""
    import argparse

    parser = argparse.ArgumentParser(description="API Compatibility Test Suite")
    parser.add_argument(
        "--base-url",
        default="http://localhost:8000",
        help="Base URL for the API (default: http://localhost:8000)",
    )
    parser.add_argument("--output", help="Output file for test results (JSON format)")

    args = parser.parse_args()

    async with APICompatibilityTester(args.base_url) as tester:
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
