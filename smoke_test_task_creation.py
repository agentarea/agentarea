#!/usr/bin/env python3
"""
Simple smoke test script to diagnose task creation workflow issues.

This script focuses on testing the specific issue where tasks show
'Task failed to start workflow' but the workflow actually runs.
"""

import asyncio
import json
import logging
import sys
import os
from datetime import datetime, UTC
from pathlib import Path
from uuid import UUID, uuid4
from typing import Any, Dict

# Set up logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class SimpleTaskDiagnostic:
    """Simple diagnostic for task creation issues."""
    
    def __init__(self):
        self.results = []
        
    def log_result(self, test: str, success: bool, details: str = "", error: Exception = None):
        """Log test result."""
        result = {
            "test": test,
            "success": success,
            "details": details,
            "error": str(error) if error else None,
            "timestamp": datetime.now(UTC).isoformat()
        }
        self.results.append(result)
        
        status = "✅" if success else "❌"
        logger.info(f"{status} {test}: {details}")
        if error:
            logger.error(f"   Error: {error}")
    
    async def test_temporal_connection(self):
        """Test basic Temporal connectivity."""
        try:
            from temporalio.client import Client
            
            # Try to connect to Temporal
            client = await Client.connect("localhost:7233")
            
            # Test basic operation
            await client.list_workflows()
            
            self.log_result("Temporal Connection", True, "Successfully connected to Temporal server")
            return True
            
        except Exception as e:
            self.log_result("Temporal Connection", False, "Failed to connect to Temporal", e)
            return False
    
    async def test_workflow_import(self):
        """Test if we can import the workflow classes."""
        try:
            # Test importing the workflow
            sys.path.insert(0, str(Path.cwd() / "core"))
            
            from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
            from agentarea_execution.models import AgentExecutionRequest
            
            self.log_result("Workflow Import", True, "Successfully imported AgentExecutionWorkflow")
            return True
            
        except Exception as e:
            self.log_result("Workflow Import", False, "Failed to import workflow classes", e)
            return False
    
    async def test_workflow_start_simulation(self):
        """Simulate starting a workflow to see what happens."""
        try:
            from temporalio.client import Client
            from temporalio.worker import Worker
            
            # Connect to Temporal
            client = await Client.connect("localhost:7233")
            
            # Import workflow
            sys.path.insert(0, str(Path.cwd() / "core"))
            from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow
            from agentarea_execution.models import AgentExecutionRequest
            
            # Create a test execution request
            test_agent_id = uuid4()
            test_task_id = uuid4()
            
            execution_request = AgentExecutionRequest(
                task_id=test_task_id,
                agent_id=test_agent_id,
                user_id="smoke_test",
                task_query="Test workflow execution",
                task_parameters={"test": True},
                workflow_metadata={}
            )
            
            workflow_id = f"smoke-test-{uuid4()}"
            
            # Try to start the workflow
            handle = await client.start_workflow(
                AgentExecutionWorkflow.run,
                execution_request,
                id=workflow_id,
                task_queue="agent-tasks"
            )
            
            self.log_result("Workflow Start", True, f"Successfully started workflow {handle.id}")
            
            # Wait a moment and check status
            await asyncio.sleep(2)
            
            try:
                description = await handle.describe()
                status = description.status.name
                self.log_result("Workflow Status Check", True, f"Workflow status: {status}")
                
                # Try to cancel it to clean up
                await handle.cancel()
                
            except Exception as status_error:
                self.log_result("Workflow Status Check", False, "Failed to check workflow status", status_error)
            
            return True
            
        except Exception as e:
            self.log_result("Workflow Start", False, "Failed to start workflow", e)
            return False
    
    async def test_task_status_logic(self):
        """Test the logic that determines if a task 'failed to start workflow'."""
        try:
            # Simulate the conditions from the API endpoint
            test_cases = [
                {"execution_id": None, "status": "pending", "expected": "failed"},
                {"execution_id": None, "status": "running", "expected": "failed"},
                {"execution_id": "some-id", "status": "failed", "expected": "failed"},
                {"execution_id": "some-id", "status": "pending", "expected": "success"},
                {"execution_id": "some-id", "status": "running", "expected": "success"},
                {"execution_id": "some-id", "status": "submitted", "expected": "failed"},
            ]
            
            logger.info("Testing task status logic from API endpoint:")
            
            for i, case in enumerate(test_cases):
                execution_id = case["execution_id"]
                status = case["status"]
                expected = case["expected"]
                
                # This is the logic from the API endpoint
                has_execution_id = execution_id is not None
                status_running_or_pending = status in ["running", "pending"]
                
                if has_execution_id and status_running_or_pending:
                    result = "success"  # Would stream events
                else:
                    result = "failed"   # Would show "Task failed to start workflow"
                
                matches_expected = result == expected
                
                logger.info(f"  Case {i+1}: execution_id={execution_id}, status={status} -> {result} (expected {expected}) {'✅' if matches_expected else '❌'}")
                
                if not matches_expected:
                    logger.warning(f"    Unexpected result for case {i+1}")
            
            # The key insight: if status is "submitted" but not "running" or "pending",
            # the API will show "Task failed to start workflow"
            logger.info("\n🔍 KEY INSIGHT: If task status is 'submitted' (not 'running'/'pending'), API shows 'failed to start workflow'")
            
            self.log_result("Task Status Logic", True, "Analyzed task status determination logic")
            return True
            
        except Exception as e:
            self.log_result("Task Status Logic", False, "Failed to test task status logic", e)
            return False
    
    async def test_environment_check(self):
        """Check environment and configuration."""
        try:
            # Check if we're in the right directory
            current_dir = Path.cwd()
            core_dir = current_dir / "core"
            
            if not core_dir.exists():
                self.log_result("Environment Check", False, f"Core directory not found at {core_dir}")
                return False
            
            # Check for key files
            key_files = [
                "core/libs/execution/agentarea_execution/workflows/agent_execution_workflow.py",
                "core/libs/tasks/agentarea_tasks/task_service.py",
                "core/libs/tasks/agentarea_tasks/temporal_task_manager.py",
            ]
            
            missing_files = []
            for file_path in key_files:
                if not (current_dir / file_path).exists():
                    missing_files.append(file_path)
            
            if missing_files:
                self.log_result("Environment Check", False, f"Missing files: {missing_files}")
                return False
            
            # Check Python path
            python_path = sys.path
            core_in_path = any("core" in path for path in python_path)
            
            details = f"Working directory: {current_dir}, Core in Python path: {core_in_path}"
            self.log_result("Environment Check", True, details)
            return True
            
        except Exception as e:
            self.log_result("Environment Check", False, "Failed environment check", e)
            return False
    
    async def run_diagnostics(self):
        """Run all diagnostic tests."""
        logger.info("🔍 Starting Task Creation Diagnostic")
        logger.info("=" * 50)
        
        tests = [
            self.test_environment_check,
            self.test_temporal_connection,
            self.test_workflow_import,
            self.test_task_status_logic,
            self.test_workflow_start_simulation,
        ]
        
        for test in tests:
            try:
                await test()
            except Exception as e:
                logger.error(f"Unexpected error in {test.__name__}: {e}")
            
            await asyncio.sleep(0.5)
        
        self.print_summary()
    
    def print_summary(self):
        """Print diagnostic summary."""
        logger.info("\n" + "=" * 50)
        logger.info("📊 DIAGNOSTIC SUMMARY")
        logger.info("=" * 50)
        
        passed = sum(1 for r in self.results if r["success"])
        total = len(self.results)
        
        logger.info(f"Tests passed: {passed}/{total}")
        
        # Show failed tests
        failed_tests = [r for r in self.results if not r["success"]]
        if failed_tests:
            logger.info("\n❌ Failed tests:")
            for test in failed_tests:
                logger.info(f"  - {test['test']}: {test['details']}")
        
        # Save results
        results_file = Path("diagnostic_results.json")
        with open(results_file, "w") as f:
            json.dump(self.results, f, indent=2, default=str)
        
        logger.info(f"\n📄 Results saved to: {results_file}")
        
        # Provide recommendations
        logger.info("\n💡 RECOMMENDATIONS:")
        logger.info("1. Check if Temporal server is running: docker-compose up temporal")
        logger.info("2. Check if worker is running: make worker (in core/ directory)")
        logger.info("3. Verify task status transitions in TemporalTaskManager.submit_task()")
        logger.info("4. Check if execution_id is being set properly after workflow start")
        logger.info("5. The issue might be that tasks stay in 'submitted' status instead of 'running'")

async def main():
    """Main entry point."""
    diagnostic = SimpleTaskDiagnostic()
    await diagnostic.run_diagnostics()

if __name__ == "__main__":
    asyncio.run(main())