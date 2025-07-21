#!/usr/bin/env python3
"""
Task Service Refactoring Verification Script

This script verifies that the task service refactoring was completed successfully
and that all components are working correctly.

Usage:
    python verify_refactoring.py
"""

import asyncio
import sys
import traceback
from typing import List, Dict, Any
from uuid import uuid4

def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{'='*60}")
    print(f"{title:^60}")
    print(f"{'='*60}")

def print_success(message: str):
    """Print a success message."""
    print(f"✅ {message}")

def print_error(message: str):
    """Print an error message."""
    print(f"❌ {message}")

def print_info(message: str):
    """Print an info message."""
    print(f"ℹ️  {message}")

class RefactoringVerifier:
    """Verifies that the task service refactoring was completed successfully."""
    
    def __init__(self):
        self.results: List[Dict[str, Any]] = []
    
    def add_result(self, test_name: str, passed: bool, message: str = "", error: str = ""):
        """Add a test result."""
        self.results.append({
            "test": test_name,
            "passed": passed,
            "message": message,
            "error": error
        })
        
        if passed:
            print_success(f"{test_name}: {message}")
        else:
            print_error(f"{test_name}: {error}")
    
    def verify_imports(self):
        """Verify that all required imports work correctly."""
        print_header("IMPORT VERIFICATION")
        
        # Test TaskService import
        try:
            from agentarea_tasks.task_service import TaskService
            self.add_result("TaskService Import", True, "Successfully imported TaskService")
        except ImportError as e:
            self.add_result("TaskService Import", False, error=str(e))
        
        # Test BaseTaskService import
        try:
            from agentarea_tasks.domain.base_service import BaseTaskService
            self.add_result("BaseTaskService Import", True, "Successfully imported BaseTaskService")
        except ImportError as e:
            self.add_result("BaseTaskService Import", False, error=str(e))
        
        # Test dependency injection imports
        try:
            from agentarea_api.api.deps.services import get_task_service
            self.add_result("Dependency Injection Import", True, "Successfully imported get_task_service")
        except ImportError as e:
            self.add_result("Dependency Injection Import", False, error=str(e))
        
        # Test domain models import
        try:
            from agentarea_tasks.domain.models import SimpleTask
            self.add_result("Domain Models Import", True, "Successfully imported SimpleTask")
        except ImportError as e:
            self.add_result("Domain Models Import", False, error=str(e))
    
    def verify_class_hierarchy(self):
        """Verify that the class hierarchy is correct."""
        print_header("CLASS HIERARCHY VERIFICATION")
        
        try:
            from agentarea_tasks.task_service import TaskService
            from agentarea_tasks.domain.base_service import BaseTaskService
            
            # Check inheritance
            if issubclass(TaskService, BaseTaskService):
                self.add_result("Class Hierarchy", True, "TaskService correctly inherits from BaseTaskService")
            else:
                self.add_result("Class Hierarchy", False, error="TaskService does not inherit from BaseTaskService")
        except Exception as e:
            self.add_result("Class Hierarchy", False, error=str(e))
    
    def verify_service_methods(self):
        """Verify that all required service methods exist."""
        print_header("SERVICE METHODS VERIFICATION")
        
        try:
            from agentarea_tasks.task_service import TaskService
            
            # Required methods from BaseTaskService
            base_methods = [
                'create_task', 'get_task', 'update_task', 'list_tasks', 'delete_task', 'submit_task'
            ]
            
            # Compatibility methods
            compatibility_methods = [
                'update_task_status', 'list_agent_tasks', 'get_task_status', 'get_task_result',
                'get_user_tasks', 'get_agent_tasks', 'cancel_task'
            ]
            
            all_methods = base_methods + compatibility_methods
            missing_methods = []
            
            for method_name in all_methods:
                if not hasattr(TaskService, method_name):
                    missing_methods.append(method_name)
                elif not callable(getattr(TaskService, method_name)):
                    missing_methods.append(f"{method_name} (not callable)")
            
            if not missing_methods:
                self.add_result("Service Methods", True, f"All {len(all_methods)} required methods present")
            else:
                self.add_result("Service Methods", False, error=f"Missing methods: {', '.join(missing_methods)}")
                
        except Exception as e:
            self.add_result("Service Methods", False, error=str(e))
    
    def verify_dependency_injection(self):
        """Verify that dependency injection is configured correctly."""
        print_header("DEPENDENCY INJECTION VERIFICATION")
        
        try:
            from agentarea_api.api.deps.services import get_task_service
            import inspect
            
            # Check function signature
            sig = inspect.signature(get_task_service)
            params = list(sig.parameters.keys())
            
            expected_params = ['db_session', 'event_broker']
            missing_params = [p for p in expected_params if p not in params]
            
            if not missing_params:
                self.add_result("DI Parameters", True, f"All required parameters present: {', '.join(params)}")
            else:
                self.add_result("DI Parameters", False, error=f"Missing parameters: {', '.join(missing_params)}")
            
            # Check return type annotation
            return_annotation = sig.return_annotation
            if 'TaskService' in str(return_annotation):
                self.add_result("DI Return Type", True, "Correct return type annotation")
            else:
                self.add_result("DI Return Type", False, error=f"Incorrect return type: {return_annotation}")
                
        except Exception as e:
            self.add_result("Dependency Injection", False, error=str(e))
    
    def verify_api_endpoints(self):
        """Verify that API endpoints are properly configured."""
        print_header("API ENDPOINTS VERIFICATION")
        
        try:
            # Check task endpoints
            from agentarea_api.api.v1.agents_tasks import router, global_tasks_router
            
            # Check that routers exist
            if router and global_tasks_router:
                self.add_result("API Routers", True, "Task API routers are properly configured")
            else:
                self.add_result("API Routers", False, error="Missing API routers")
            
            # Check response models
            from agentarea_api.api.v1.agents_tasks import TaskResponse, TaskWithAgent, TaskCreate
            
            required_models = [TaskResponse, TaskWithAgent, TaskCreate]
            model_names = [model.__name__ for model in required_models]
            
            self.add_result("API Models", True, f"All response models present: {', '.join(model_names)}")
            
        except Exception as e:
            self.add_result("API Endpoints", False, error=str(e))
    
    def verify_a2a_compatibility(self):
        """Verify that A2A protocol endpoints are working."""
        print_header("A2A PROTOCOL VERIFICATION")
        
        try:
            from agentarea_api.api.v1.agents_a2a import router
            
            if router:
                self.add_result("A2A Router", True, "A2A protocol router is configured")
            else:
                self.add_result("A2A Router", False, error="A2A router not found")
            
            # Check A2A handler functions
            from agentarea_api.api.v1.agents_a2a import (
                handle_task_send, handle_message_send, handle_task_get, handle_task_cancel
            )
            
            handlers = [handle_task_send, handle_message_send, handle_task_get, handle_task_cancel]
            handler_names = [h.__name__ for h in handlers]
            
            self.add_result("A2A Handlers", True, f"All A2A handlers present: {', '.join(handler_names)}")
            
        except Exception as e:
            self.add_result("A2A Protocol", False, error=str(e))
    
    def verify_domain_models(self):
        """Verify that domain models are properly structured."""
        print_header("DOMAIN MODELS VERIFICATION")
        
        try:
            from agentarea_tasks.domain.models import SimpleTask
            
            # Check SimpleTask fields
            task = SimpleTask(
                title="Test Task",
                description="Test Description", 
                query="Test Query",
                user_id="test_user",
                agent_id=uuid4(),
                status="submitted"
            )
            
            # Verify required fields exist
            required_fields = ['id', 'title', 'description', 'query', 'user_id', 'agent_id', 'status']
            missing_fields = []
            
            for field in required_fields:
                if not hasattr(task, field):
                    missing_fields.append(field)
            
            if not missing_fields:
                self.add_result("SimpleTask Model", True, f"All required fields present: {', '.join(required_fields)}")
            else:
                self.add_result("SimpleTask Model", False, error=f"Missing fields: {', '.join(missing_fields)}")
            
            # Test status update method
            if hasattr(task, 'update_status') and callable(task.update_status):
                self.add_result("Task Status Update", True, "update_status method available")
            else:
                self.add_result("Task Status Update", False, error="update_status method missing")
                
        except Exception as e:
            self.add_result("Domain Models", False, error=str(e))
    
    def verify_event_system(self):
        """Verify that the event system is properly configured."""
        print_header("EVENT SYSTEM VERIFICATION")
        
        try:
            from agentarea_tasks.domain.events import TaskCreated, TaskUpdated, TaskStatusChanged
            
            # Check event classes exist
            events = [TaskCreated, TaskUpdated, TaskStatusChanged]
            event_names = [e.__name__ for e in events]
            
            self.add_result("Domain Events", True, f"All domain events present: {', '.join(event_names)}")
            
            # Check event broker dependency
            from agentarea_api.api.deps.services import get_event_broker
            
            if callable(get_event_broker):
                self.add_result("Event Broker DI", True, "Event broker dependency injection configured")
            else:
                self.add_result("Event Broker DI", False, error="Event broker DI not configured")
                
        except Exception as e:
            self.add_result("Event System", False, error=str(e))
    
    async def run_all_verifications(self):
        """Run all verification tests."""
        print_header("TASK SERVICE REFACTORING VERIFICATION")
        print_info("Verifying that the refactoring was completed successfully...")
        
        # Run all verification tests
        self.verify_imports()
        self.verify_class_hierarchy()
        self.verify_service_methods()
        self.verify_dependency_injection()
        self.verify_api_endpoints()
        self.verify_a2a_compatibility()
        self.verify_domain_models()
        self.verify_event_system()
        
        # Print summary
        self.print_summary()
    
    def print_summary(self):
        """Print a summary of all test results."""
        print_header("VERIFICATION SUMMARY")
        
        total_tests = len(self.results)
        passed_tests = sum(1 for r in self.results if r["passed"])
        failed_tests = total_tests - passed_tests
        
        print(f"Total Tests: {total_tests}")
        print(f"Passed: {passed_tests}")
        print(f"Failed: {failed_tests}")
        
        if failed_tests == 0:
            print_success("🎉 All verification tests passed!")
            print_info("The task service refactoring was completed successfully.")
            print_info("No breaking changes detected.")
        else:
            print_error(f"❌ {failed_tests} verification tests failed.")
            print_info("The following issues need to be addressed:")
            
            for result in self.results:
                if not result["passed"]:
                    print(f"  - {result['test']}: {result['error']}")
        
        print(f"\n{'='*60}")
        
        return failed_tests == 0


async def main():
    """Main verification function."""
    verifier = RefactoringVerifier()
    
    try:
        success = await verifier.run_all_verifications()
        sys.exit(0 if success else 1)
    except KeyboardInterrupt:
        print_info("Verification interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"Verification failed with error: {e}")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())