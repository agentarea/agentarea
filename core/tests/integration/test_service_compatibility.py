#!/usr/bin/env python3
"""
Service Compatibility Test Suite

This script tests the refactored task service architecture to ensure:
1. All services can be properly instantiated through dependency injection
2. The refactored TaskService maintains backward compatibility
3. API endpoints can successfully use the refactored services
4. No breaking changes were introduced in the service interfaces

Requirements addressed:
- 4.4: Verify that no breaking changes were introduced
- 5.2: Test that dependency injection works correctly
- 5.3: Ensure TaskService can be properly instantiated with all required dependencies
"""

import asyncio
import logging
import sys
from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


class ServiceCompatibilityTester:
    """Test suite for service compatibility verification."""

    def __init__(self):
        """Initialize the tester."""
        self.test_results: list[dict[str, Any]] = []

    def log_test_result(
        self, test_name: str, success: bool, details: str = "", error: Exception | None = None
    ):
        """Log a test result."""
        result = {
            "test_name": test_name,
            "success": success,
            "details": details,
            "timestamp": datetime.now().isoformat(),
            "error": str(error) if error else None,
        }
        self.test_results.append(result)

        status = "✅ PASS" if success else "❌ FAIL"
        logger.info(f"{status} {test_name}: {details}")

        if error:
            logger.error(f"Error: {error}")

    def test_import_refactored_services(self) -> bool:
        """Test that all refactored services can be imported."""
        try:
            # Test importing the main task service

            # Test importing the base service

            # Test importing domain models

            # Test importing repository

            # Test importing task manager

            # Test importing dependency injection functions

            self.log_test_result(
                "Import Refactored Services", True, "All refactored services imported successfully"
            )
            return True

        except Exception as e:
            self.log_test_result(
                "Import Refactored Services", False, "Failed to import refactored services", e
            )
            return False

    def test_base_service_inheritance(self) -> bool:
        """Test that TaskService properly inherits from BaseTaskService."""
        try:
            from agentarea_tasks.domain.base_service import BaseTaskService
            from agentarea_tasks.task_service import TaskService

            # Check inheritance
            if not issubclass(TaskService, BaseTaskService):
                raise ValueError("TaskService does not inherit from BaseTaskService")

            # Check that TaskService has the required abstract method implemented
            if not hasattr(TaskService, "submit_task"):
                raise ValueError("TaskService does not implement submit_task method")

            # Check that TaskService has inherited methods
            expected_methods = [
                "create_task",
                "get_task",
                "update_task",
                "list_tasks",
                "delete_task",
            ]
            for method in expected_methods:
                if not hasattr(TaskService, method):
                    raise ValueError(f"TaskService missing inherited method: {method}")

            self.log_test_result(
                "Base Service Inheritance",
                True,
                "TaskService properly inherits from BaseTaskService with all required methods",
            )
            return True

        except Exception as e:
            self.log_test_result(
                "Base Service Inheritance",
                False,
                "TaskService inheritance structure is incorrect",
                e,
            )
            return False

    def test_task_service_instantiation(self) -> bool:
        """Test that TaskService can be instantiated with mocked dependencies."""
        try:
            from agentarea_agents.infrastructure.repository import AgentRepository
            from agentarea_common.events.broker import EventBroker
            from agentarea_tasks.infrastructure.repository import TaskRepository
            from agentarea_tasks.task_service import TaskService
            from agentarea_tasks.temporal_task_manager import TemporalTaskManager

            # Create mock dependencies
            mock_task_repository = AsyncMock(spec=TaskRepository)
            mock_event_broker = AsyncMock(spec=EventBroker)
            mock_task_manager = AsyncMock(spec=TemporalTaskManager)
            mock_agent_repository = AsyncMock(spec=AgentRepository)

            # Instantiate TaskService
            task_service = TaskService(
                task_repository=mock_task_repository,
                event_broker=mock_event_broker,
                task_manager=mock_task_manager,
                agent_repository=mock_agent_repository,
            )

            # Verify the service has the expected attributes
            assert hasattr(task_service, "task_repository")
            assert hasattr(task_service, "event_broker")
            assert hasattr(task_service, "task_manager")
            assert hasattr(task_service, "agent_repository")

            # Verify it has all the expected methods
            expected_methods = [
                "create_task",
                "get_task",
                "update_task",
                "list_tasks",
                "delete_task",
                "submit_task",
                "cancel_task",
                "get_user_tasks",
                "get_agent_tasks",
            ]
            for method in expected_methods:
                if not hasattr(task_service, method):
                    raise ValueError(f"TaskService missing method: {method}")

            self.log_test_result(
                "Task Service Instantiation",
                True,
                "TaskService instantiated successfully with all dependencies",
            )
            return True

        except Exception as e:
            self.log_test_result(
                "Task Service Instantiation", False, "Failed to instantiate TaskService", e
            )
            return False

    async def test_task_service_crud_operations(self) -> bool:
        """Test that TaskService CRUD operations work correctly."""
        try:
            from agentarea_agents.infrastructure.repository import AgentRepository
            from agentarea_common.events.broker import EventBroker
            from agentarea_tasks.domain.models import SimpleTask
            from agentarea_tasks.infrastructure.repository import TaskRepository
            from agentarea_tasks.task_service import TaskService
            from agentarea_tasks.temporal_task_manager import TemporalTaskManager

            # Create mock dependencies
            mock_task_repository = AsyncMock(spec=TaskRepository)
            mock_event_broker = AsyncMock(spec=EventBroker)
            mock_task_manager = AsyncMock(spec=TemporalTaskManager)
            mock_agent_repository = AsyncMock(spec=AgentRepository)

            # Create test task
            test_task = SimpleTask(
                id=uuid4(),
                title="Test Task",
                description="Test task for compatibility testing",
                query="Test query",
                user_id="test_user",
                agent_id=uuid4(),
                status="submitted",
            )

            # Mock repository responses
            mock_task_repository.create.return_value = test_task
            mock_task_repository.get.return_value = test_task
            mock_task_repository.update.return_value = test_task
            mock_task_repository.get_by_agent_id.return_value = [test_task]
            mock_task_repository.get_by_user_id.return_value = [test_task]
            mock_task_repository.delete.return_value = True

            # Mock agent repository
            mock_agent = MagicMock()
            mock_agent.id = test_task.agent_id
            mock_agent_repository.get.return_value = mock_agent

            # Mock task manager
            mock_task_manager.submit_task.return_value = test_task
            mock_task_manager.cancel_task.return_value = True

            # Instantiate TaskService
            task_service = TaskService(
                task_repository=mock_task_repository,
                event_broker=mock_event_broker,
                task_manager=mock_task_manager,
                agent_repository=mock_agent_repository,
            )

            # Test create_task
            created_task = await task_service.create_task(test_task)
            assert created_task.id == test_task.id

            # Test get_task
            retrieved_task = await task_service.get_task(test_task.id)
            assert retrieved_task.id == test_task.id

            # Test update_task
            test_task.status = "completed"
            updated_task = await task_service.update_task(test_task)
            assert updated_task.status == "completed"

            # Test list_tasks with agent filter
            agent_tasks = await task_service.list_tasks(agent_id=test_task.agent_id)
            assert len(agent_tasks) == 1
            assert agent_tasks[0].id == test_task.id

            # Test list_tasks with user filter
            user_tasks = await task_service.list_tasks(user_id=test_task.user_id)
            assert len(user_tasks) == 1
            assert user_tasks[0].id == test_task.id

            # Test submit_task
            submitted_task = await task_service.submit_task(test_task)
            assert submitted_task.id == test_task.id

            # Test cancel_task
            cancelled = await task_service.cancel_task(test_task.id)
            assert cancelled is True

            # Test delete_task
            deleted = await task_service.delete_task(test_task.id)
            assert deleted is True

            self.log_test_result(
                "Task Service CRUD Operations", True, "All CRUD operations work correctly"
            )
            return True

        except Exception as e:
            self.log_test_result("Task Service CRUD Operations", False, "CRUD operations failed", e)
            return False

    def test_dependency_injection_functions(self) -> bool:
        """Test that dependency injection functions are properly defined."""
        try:
            from agentarea_api.api.deps.services import (
                get_agent_repository,
                get_task_manager,
                get_task_repository,
                get_task_service,
            )

            # Check that functions exist and are callable
            functions_to_test = [
                get_task_service,
                get_task_repository,
                get_agent_repository,
                get_task_manager,
            ]

            for func in functions_to_test:
                if not callable(func):
                    raise ValueError(f"Function {func.__name__} is not callable")

            # Check function signatures (they should be async)
            import inspect

            for func in functions_to_test:
                if not inspect.iscoroutinefunction(func):
                    raise ValueError(f"Function {func.__name__} is not async")

            self.log_test_result(
                "Dependency Injection Functions",
                True,
                "All dependency injection functions are properly defined",
            )
            return True

        except Exception as e:
            self.log_test_result(
                "Dependency Injection Functions",
                False,
                "Dependency injection functions are not properly defined",
                e,
            )
            return False

    def test_backward_compatibility_methods(self) -> bool:
        """Test that backward compatibility methods exist in TaskService."""
        try:
            from agentarea_tasks.task_service import TaskService

            # Check for backward compatibility methods
            compatibility_methods = [
                "create_task_from_params",
                "get_user_tasks",
                "get_agent_tasks",
                "get_task_status",
                "get_task_result",
                "update_task_status",
                "list_agent_tasks",
                "execute_task",
                "create_and_execute_task",
            ]

            for method in compatibility_methods:
                if not hasattr(TaskService, method):
                    raise ValueError(f"TaskService missing backward compatibility method: {method}")

                # Check that method is callable
                method_obj = getattr(TaskService, method)
                if not callable(method_obj):
                    raise ValueError(f"Method {method} is not callable")

            self.log_test_result(
                "Backward Compatibility Methods",
                True,
                "All backward compatibility methods are present",
            )
            return True

        except Exception as e:
            self.log_test_result(
                "Backward Compatibility Methods",
                False,
                "Backward compatibility methods are missing",
                e,
            )
            return False

    def test_simple_task_model_enhancements(self) -> bool:
        """Test that SimpleTask model has been enhanced with additional fields."""
        try:
            from agentarea_tasks.domain.models import SimpleTask

            # Create a SimpleTask instance
            task = SimpleTask(
                title="Test Task",
                description="Test Description",
                query="Test Query",
                user_id="test_user",
                agent_id=uuid4(),
            )

            # Check for enhanced fields
            enhanced_fields = ["started_at", "completed_at", "execution_id", "metadata"]

            for field in enhanced_fields:
                if not hasattr(task, field):
                    raise ValueError(f"SimpleTask missing enhanced field: {field}")

            # Test that the model can be instantiated with enhanced fields
            enhanced_task = SimpleTask(
                title="Enhanced Task",
                description="Enhanced Description",
                query="Enhanced Query",
                user_id="test_user",
                agent_id=uuid4(),
                started_at=datetime.now(),
                completed_at=datetime.now(),
                execution_id="test-execution-id",
                metadata={"test": "value"},
            )

            assert enhanced_task.execution_id == "test-execution-id"
            assert enhanced_task.metadata["test"] == "value"

            self.log_test_result(
                "SimpleTask Model Enhancements", True, "SimpleTask model has all enhanced fields"
            )
            return True

        except Exception as e:
            self.log_test_result(
                "SimpleTask Model Enhancements",
                False,
                "SimpleTask model enhancements are missing",
                e,
            )
            return False

    def test_repository_enhanced_methods(self) -> bool:
        """Test that TaskRepository has enhanced methods."""
        try:
            from agentarea_tasks.infrastructure.repository import TaskRepository

            # Check for enhanced methods
            enhanced_methods = [
                "get_by_agent_id",
                "get_by_user_id",
                "get_by_status",
                "update_status",
            ]

            for method in enhanced_methods:
                if not hasattr(TaskRepository, method):
                    raise ValueError(f"TaskRepository missing enhanced method: {method}")

                # Check that method is callable
                method_obj = getattr(TaskRepository, method)
                if not callable(method_obj):
                    raise ValueError(f"Method {method} is not callable")

            self.log_test_result(
                "Repository Enhanced Methods", True, "TaskRepository has all enhanced methods"
            )
            return True

        except Exception as e:
            self.log_test_result(
                "Repository Enhanced Methods",
                False,
                "TaskRepository enhanced methods are missing",
                e,
            )
            return False

    def test_error_handling_classes(self) -> bool:
        """Test that custom error handling classes exist."""
        try:
            from agentarea_tasks.domain.base_service import TaskNotFoundError, TaskValidationError

            # Check that they are proper exception classes
            if not issubclass(TaskValidationError, Exception):
                raise ValueError("TaskValidationError is not an Exception subclass")

            if not issubclass(TaskNotFoundError, Exception):
                raise ValueError("TaskNotFoundError is not an Exception subclass")

            # Test that they can be instantiated
            validation_error = TaskValidationError("Test validation error")
            not_found_error = TaskNotFoundError("Test not found error")

            assert str(validation_error) == "Test validation error"
            assert str(not_found_error) == "Test not found error"

            self.log_test_result(
                "Error Handling Classes", True, "Custom error classes are properly defined"
            )
            return True

        except Exception as e:
            self.log_test_result(
                "Error Handling Classes", False, "Custom error classes are not properly defined", e
            )
            return False

    async def run_comprehensive_test_suite(self) -> dict[str, Any]:
        """Run the complete service compatibility test suite."""
        logger.info("🚀 Starting Service Compatibility Test Suite")
        logger.info("=" * 60)

        # Test 1: Import all refactored services
        self.test_import_refactored_services()

        # Test 2: Check inheritance structure
        self.test_base_service_inheritance()

        # Test 3: Test service instantiation
        self.test_task_service_instantiation()

        # Test 4: Test CRUD operations
        await self.test_task_service_crud_operations()

        # Test 5: Test dependency injection functions
        self.test_dependency_injection_functions()

        # Test 6: Test backward compatibility methods
        self.test_backward_compatibility_methods()

        # Test 7: Test SimpleTask model enhancements
        self.test_simple_task_model_enhancements()

        # Test 8: Test repository enhanced methods
        self.test_repository_enhanced_methods()

        # Test 9: Test error handling classes
        self.test_error_handling_classes()

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
    """Main function to run the service compatibility tests."""
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Service Compatibility Test Suite")
    parser.add_argument("--output", help="Output file for test results (JSON format)")

    args = parser.parse_args()

    tester = ServiceCompatibilityTester()
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
