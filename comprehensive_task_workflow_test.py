#!/usr/bin/env python3
"""
Comprehensive Task Workflow Test

This script tests the complete task creation and workflow execution flow
to verify that the "Task failed to start workflow" issue has been resolved.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime
from pathlib import Path
from uuid import uuid4, UUID
from typing import Any, Dict

# Add the core directory to Python path
sys.path.insert(0, str(Path.cwd() / "core"))

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class TaskWorkflowTester:
    """Comprehensive tester for task workflow integration."""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.now().isoformat(),
            "tests": [],
            "summary": {}
        }
    
    async def run_all_tests(self):
        """Run all diagnostic tests."""
        logger.info("🚀 Starting Comprehensive Task Workflow Tests")
        logger.info("=" * 60)
        
        tests = [
            ("Database Connection", self.test_database_connection),
            ("Temporal Connection", self.test_temporal_connection),
            ("Task Creation Flow", self.test_task_creation_flow),
            ("Workflow Integration", self.test_workflow_integration),
            ("API Endpoint Logic", self.test_api_endpoint_logic),
            ("End-to-End Simulation", self.test_end_to_end_simulation)
        ]
        
        for test_name, test_func in tests:
            logger.info(f"\n📋 Running: {test_name}")
            try:
                result = await test_func()
                self.results["tests"].append({
                    "name": test_name,
                    "status": "PASS" if result.get("success", False) else "FAIL",
                    "details": result.get("details"),
                    "error": result.get("error")
                })
                logger.info(f"✅ {test_name}: {'PASS' if result.get('success', False) else 'FAIL'}")
            except Exception as e:
                logger.error(f"❌ {test_name}: ERROR - {e}")
                self.results["tests"].append({
                    "name": test_name,
                    "status": "ERROR",
                    "details": None,
                    "error": str(e)
                })
        
        await self.generate_summary()
        await self.save_results()
        
    async def test_database_connection(self) -> Dict[str, Any]:
        """Test database connectivity and task repository."""
        try:
            from agentarea_common.config.database import get_db
            from agentarea_tasks.infrastructure.repository import TaskRepository
            
            # Test database connection
            db = get_db()
            task_repo = TaskRepository(db)
            
            # Try to list tasks (should work even if empty)
            tasks = await task_repo.list_tasks(limit=1)
            
            return {
                "success": True,
                "details": {
                    "database_connected": True,
                    "repository_functional": True,
                    "sample_task_count": len(tasks)
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def test_temporal_connection(self) -> Dict[str, Any]:
        """Test Temporal server connectivity."""
        try:
            from temporalio.client import Client
            
            # Connect to Temporal
            client = await Client.connect("localhost:7233")
            
            # Test connection by getting service info
            service_info = await client.workflow_service.get_system_info()
            
            return {
                "success": True,
                "details": {
                    "temporal_connected": True,
                    "server_version": getattr(service_info, 'server_version', 'unknown'),
                    "capabilities": bool(getattr(service_info, 'capabilities', None))
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def test_task_creation_flow(self) -> Dict[str, Any]:
        """Test the basic task creation flow."""
        try:
            from agentarea_tasks.task_service import TaskService
            from agentarea_tasks.domain.models import SimpleTask
            
            # Create task service
            task_service = TaskService()
            
            # Create a test task
            test_task = SimpleTask(
                id=uuid4(),
                title="Test Task Creation",
                description="Testing task creation flow",
                query="test query",
                user_id="test_user",
                agent_id=uuid4(),
                status="pending",
                task_parameters={"test": True}
            )
            
            # Create the task
            created_task = await task_service.create_task(test_task)
            
            return {
                "success": True,
                "details": {
                    "task_created": True,
                    "task_id": str(created_task.id),
                    "initial_status": created_task.status,
                    "has_execution_id": created_task.execution_id is not None
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def test_workflow_integration(self) -> Dict[str, Any]:
        """Test workflow integration through TemporalTaskManager."""
        try:
            from agentarea_tasks.temporal_task_manager import TemporalTaskManager
            from agentarea_tasks.infrastructure.repository import TaskRepository
            from agentarea_tasks.domain.models import SimpleTask
            from agentarea_common.config.database import get_db
            
            # Setup dependencies
            db = get_db()
            task_repo = TaskRepository(db)
            task_manager = TemporalTaskManager(task_repo)
            
            # Create a test task
            test_task = SimpleTask(
                id=uuid4(),
                title="Test Workflow Integration",
                description="Testing workflow integration",
                query="test workflow query",
                user_id="test_user",
                agent_id=uuid4(),
                status="pending",
                task_parameters={"workflow_test": True}
            )
            
            # Submit task through task manager
            submitted_task = await task_manager.submit_task(test_task)
            
            return {
                "success": True,
                "details": {
                    "workflow_submitted": True,
                    "task_id": str(submitted_task.id),
                    "final_status": submitted_task.status,
                    "has_execution_id": submitted_task.execution_id is not None,
                    "execution_id": submitted_task.execution_id,
                    "status_is_running": submitted_task.status == "running"
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def test_api_endpoint_logic(self) -> Dict[str, Any]:
        """Test the API endpoint logic that determines success/failure."""
        try:
            # Simulate the API endpoint logic from agents_tasks.py
            
            # Test case 1: Task with execution_id and running status (should succeed)
            test_task_success = type('Task', (), {
                'execution_id': 'test-execution-123',
                'status': 'running'
            })()
            
            success_condition = (test_task_success.execution_id and 
                               test_task_success.status in ["running", "pending"])
            
            # Test case 2: Task without execution_id (should fail)
            test_task_fail_no_exec = type('Task', (), {
                'execution_id': None,
                'status': 'running'
            })()
            
            fail_condition_1 = (test_task_fail_no_exec.execution_id and 
                              test_task_fail_no_exec.status in ["running", "pending"])
            
            # Test case 3: Task with execution_id but wrong status (should fail)
            test_task_fail_status = type('Task', (), {
                'execution_id': 'test-execution-456',
                'status': 'submitted'
            })()
            
            fail_condition_2 = (test_task_fail_status.execution_id and 
                              test_task_fail_status.status in ["running", "pending"])
            
            return {
                "success": True,
                "details": {
                    "api_logic_tested": True,
                    "success_case": {
                        "execution_id": test_task_success.execution_id,
                        "status": test_task_success.status,
                        "would_succeed": success_condition
                    },
                    "fail_case_no_exec_id": {
                        "execution_id": test_task_fail_no_exec.execution_id,
                        "status": test_task_fail_no_exec.status,
                        "would_succeed": fail_condition_1
                    },
                    "fail_case_wrong_status": {
                        "execution_id": test_task_fail_status.execution_id,
                        "status": test_task_fail_status.status,
                        "would_succeed": fail_condition_2
                    }
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def test_end_to_end_simulation(self) -> Dict[str, Any]:
        """Test end-to-end task creation and workflow execution simulation."""
        try:
            from agentarea_tasks.task_service import TaskService
            
            # Create task service
            task_service = TaskService()
            
            # Simulate the API endpoint call
            test_agent_id = uuid4()
            
            # This should create a task and start a workflow
            created_task = await task_service.create_and_execute_task_with_workflow(
                agent_id=test_agent_id,
                description="End-to-end test task",
                parameters={"e2e_test": True},
                user_id="test_user",
                enable_agent_communication=True
            )
            
            # Check if the task meets API success criteria
            api_success_criteria = (created_task.execution_id and 
                                  created_task.status in ["running", "pending"])
            
            return {
                "success": True,
                "details": {
                    "task_created": True,
                    "task_id": str(created_task.id),
                    "agent_id": str(test_agent_id),
                    "final_status": created_task.status,
                    "execution_id": created_task.execution_id,
                    "has_execution_id": created_task.execution_id is not None,
                    "api_success_criteria_met": api_success_criteria,
                    "would_show_error": not api_success_criteria
                }
            }
            
        except Exception as e:
            return {
                "success": False,
                "error": str(e)
            }
    
    async def generate_summary(self):
        """Generate test summary."""
        total_tests = len(self.results["tests"])
        passed = len([t for t in self.results["tests"] if t["status"] == "PASS"])
        failed = len([t for t in self.results["tests"] if t["status"] == "FAIL"])
        errors = len([t for t in self.results["tests"] if t["status"] == "ERROR"])
        
        # Analyze results
        workflow_integration_test = next(
            (t for t in self.results["tests"] if t["name"] == "Workflow Integration"), 
            None
        )
        
        e2e_test = next(
            (t for t in self.results["tests"] if t["name"] == "End-to-End Simulation"), 
            None
        )
        
        fix_status = "UNKNOWN"
        if workflow_integration_test and e2e_test:
            if (workflow_integration_test["status"] == "PASS" and 
                e2e_test["status"] == "PASS"):
                
                # Check if the fix criteria are met
                workflow_details = workflow_integration_test.get("details", {})
                e2e_details = e2e_test.get("details", {})
                
                if (workflow_details.get("status_is_running") and 
                    workflow_details.get("has_execution_id") and
                    e2e_details.get("api_success_criteria_met")):
                    fix_status = "WORKING"
                else:
                    fix_status = "PARTIAL"
            else:
                fix_status = "BROKEN"
        
        self.results["summary"] = {
            "total_tests": total_tests,
            "passed": passed,
            "failed": failed,
            "errors": errors,
            "success_rate": f"{(passed/total_tests)*100:.1f}%" if total_tests > 0 else "0%",
            "fix_status": fix_status,
            "key_findings": self._extract_key_findings()
        }
        
        # Log summary
        logger.info("\n" + "=" * 60)
        logger.info("📊 TEST SUMMARY")
        logger.info("=" * 60)
        logger.info(f"Total Tests: {total_tests}")
        logger.info(f"Passed: {passed}")
        logger.info(f"Failed: {failed}")
        logger.info(f"Errors: {errors}")
        logger.info(f"Success Rate: {self.results['summary']['success_rate']}")
        logger.info(f"Fix Status: {fix_status}")
        
        if fix_status == "WORKING":
            logger.info("\n🎉 The 'Task failed to start workflow' issue appears to be FIXED!")
        elif fix_status == "PARTIAL":
            logger.info("\n⚠️  The fix is partially working but needs attention.")
        elif fix_status == "BROKEN":
            logger.info("\n❌ The 'Task failed to start workflow' issue is still present.")
    
    def _extract_key_findings(self) -> Dict[str, Any]:
        """Extract key findings from test results."""
        findings = {}
        
        for test in self.results["tests"]:
            if test["name"] == "Workflow Integration" and test["details"]:
                findings["workflow_integration"] = {
                    "status_after_submit": test["details"].get("final_status"),
                    "has_execution_id": test["details"].get("has_execution_id"),
                    "execution_id": test["details"].get("execution_id")
                }
            
            elif test["name"] == "End-to-End Simulation" and test["details"]:
                findings["e2e_simulation"] = {
                    "api_criteria_met": test["details"].get("api_success_criteria_met"),
                    "would_show_error": test["details"].get("would_show_error"),
                    "final_status": test["details"].get("final_status")
                }
        
        return findings
    
    async def save_results(self):
        """Save test results to file."""
        results_file = Path("comprehensive_task_workflow_test_results.json")
        
        with open(results_file, "w") as f:
            json.dump(self.results, f, indent=2)
        
        logger.info(f"\n💾 Results saved to: {results_file}")

async def main():
    """Main test runner."""
    tester = TaskWorkflowTester()
    await tester.run_all_tests()

if __name__ == "__main__":
    asyncio.run(main())