#!/usr/bin/env python3
"""
Debug script to investigate task status transitions in TemporalTaskManager.

This script specifically investigates why tasks show 'Task failed to start workflow'
when the workflow actually starts successfully.
"""

import asyncio
import json
import logging
import sys
from datetime import datetime, UTC
from pathlib import Path
from uuid import UUID, uuid4
from typing import Any, Dict

# Set up logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Add core to Python path
sys.path.insert(0, str(Path.cwd() / "core"))

class TaskStatusDebugger:
    """Debug task status transitions."""
    
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
    
    async def debug_temporal_task_manager_flow(self):
        """Debug the exact flow in TemporalTaskManager.submit_task()."""
        try:
            from agentarea_tasks.domain.models import SimpleTask
            from agentarea_common.workflow.temporal_executor import TemporalWorkflowExecutor
            from agentarea_common.config import get_settings
            from agentarea_execution.models import AgentExecutionRequest
            
            # Create a test task
            test_task = SimpleTask(
                id=uuid4(),
                title="Debug task status",
                description="Testing task status transitions",
                query="Debug task status transitions",
                user_id="debug_user",
                agent_id=uuid4(),
                status="pending",
                task_parameters={"debug": True}
            )
            
            logger.info(f"🔍 Created test task: {test_task.id}")
            logger.info(f"   Initial status: {test_task.status}")
            logger.info(f"   Initial execution_id: {test_task.execution_id}")
            
            # Step 1: Create TemporalWorkflowExecutor (like TemporalTaskManager does)
            settings = get_settings()
            temporal_executor = TemporalWorkflowExecutor(
                namespace=settings.workflow.TEMPORAL_NAMESPACE,
                server_url=settings.workflow.TEMPORAL_SERVER_URL
            )
            
            logger.info(f"🔍 Created TemporalWorkflowExecutor")
            logger.info(f"   Namespace: {settings.workflow.TEMPORAL_NAMESPACE}")
            logger.info(f"   Server URL: {settings.workflow.TEMPORAL_SERVER_URL}")
            
            # Step 2: Create AgentExecutionRequest (like TemporalTaskManager.submit_task does)
            execution_request = AgentExecutionRequest(
                task_id=test_task.id,
                agent_id=test_task.agent_id,
                user_id=test_task.user_id,
                task_query=test_task.query,
                task_parameters=test_task.task_parameters or {},
                workflow_metadata={}
            )
            
            logger.info(f"🔍 Created AgentExecutionRequest")
            logger.info(f"   Task ID: {execution_request.task_id}")
            logger.info(f"   Agent ID: {execution_request.agent_id}")
            
            # Step 3: Start workflow (like TemporalTaskManager.submit_task does)
            workflow_id = f"task-{test_task.id}"
            
            logger.info(f"🔍 Starting workflow with ID: {workflow_id}")
            
            # Convert to dict format (like temporal_executor.py does)
            args_dict = {
                "task_id": str(execution_request.task_id),
                "agent_id": str(execution_request.agent_id),
                "user_id": execution_request.user_id,
                "task_query": execution_request.task_query,
                "task_parameters": execution_request.task_parameters,
                "timeout_seconds": execution_request.timeout_seconds,
                "max_reasoning_iterations": execution_request.max_reasoning_iterations,
                "enable_agent_communication": execution_request.enable_agent_communication,
                "requires_human_approval": execution_request.requires_human_approval,
                "workflow_metadata": execution_request.workflow_metadata
            }
            
            from agentarea_common.workflow.executor import WorkflowConfig
            config = WorkflowConfig(task_queue="agent-tasks")
            
            # This is the critical step - start the workflow
            execution_id = await temporal_executor.start_workflow(
                workflow_name="AgentExecutionWorkflow",
                workflow_id=workflow_id,
                args=args_dict,
                config=config
            )
            
            logger.info(f"🔍 Workflow started successfully!")
            logger.info(f"   Execution ID: {execution_id}")
            
            # Step 4: Update task status (like TemporalTaskManager.submit_task does)
            test_task.execution_id = execution_id
            test_task.status = "submitted"  # This is what TemporalTaskManager sets
            
            logger.info(f"🔍 Task updated after workflow start:")
            logger.info(f"   Status: {test_task.status}")
            logger.info(f"   Execution ID: {test_task.execution_id}")
            
            # Step 5: Check what the API endpoint logic would do
            has_execution_id = test_task.execution_id is not None
            status_running_or_pending = test_task.status in ["running", "pending"]
            
            logger.info(f"🔍 API endpoint logic check:")
            logger.info(f"   Has execution_id: {has_execution_id}")
            logger.info(f"   Status is running/pending: {status_running_or_pending}")
            
            if has_execution_id and status_running_or_pending:
                api_result = "Would stream events (SUCCESS)"
            else:
                api_result = "Would show 'Task failed to start workflow' (FAILURE)"
            
            logger.info(f"   API Result: {api_result}")
            
            # Step 6: Check actual workflow status
            await asyncio.sleep(1)
            workflow_status = await temporal_executor.get_workflow_status(workflow_id)
            logger.info(f"🔍 Actual workflow status: {workflow_status.status.value}")
            
            # The problem is clear now!
            if test_task.status == "submitted" and workflow_status.status.value == "RUNNING":
                logger.error("🚨 PROBLEM IDENTIFIED:")
                logger.error("   - Task status is 'submitted' (not 'running' or 'pending')")
                logger.error("   - But workflow is actually RUNNING")
                logger.error("   - API endpoint requires status to be 'running' or 'pending'")
                logger.error("   - This causes 'Task failed to start workflow' message")
                
                self.log_result("Task Status Issue", False, 
                              f"Task status '{test_task.status}' doesn't match workflow status '{workflow_status.status.value}'")
            else:
                self.log_result("Task Status Issue", True, "Task and workflow statuses are consistent")
            
            # Clean up
            await temporal_executor.cancel_workflow(workflow_id)
            
            return True
            
        except Exception as e:
            self.log_result("Temporal Task Manager Flow", False, "Failed to debug task manager flow", e)
            return False
    
    async def investigate_status_update_timing(self):
        """Investigate if there's a timing issue with status updates."""
        try:
            logger.info("🔍 Investigating status update timing...")
            
            # The issue might be that TemporalTaskManager sets status to "submitted"
            # but never updates it to "running" when the workflow actually starts
            
            # Let's check the TemporalTaskManager code
            temporal_task_manager_file = Path.cwd() / "core" / "libs" / "tasks" / "agentarea_tasks" / "temporal_task_manager.py"
            
            if temporal_task_manager_file.exists():
                with open(temporal_task_manager_file, 'r') as f:
                    content = f.read()
                
                # Look for status updates
                if 'status = "submitted"' in content:
                    logger.info("✅ Found: Task status set to 'submitted' in TemporalTaskManager")
                
                if 'status = "running"' in content:
                    logger.info("✅ Found: Task status set to 'running' in TemporalTaskManager")
                else:
                    logger.warning("⚠️  NOT FOUND: Task status never set to 'running' in TemporalTaskManager")
                    logger.warning("   This might be the root cause!")
                
                # Check if there's any workflow status monitoring
                if 'workflow_status' in content or 'get_workflow_status' in content:
                    logger.info("✅ Found: Workflow status monitoring in TemporalTaskManager")
                else:
                    logger.warning("⚠️  NOT FOUND: No workflow status monitoring in TemporalTaskManager")
                    logger.warning("   Tasks might stay 'submitted' forever")
                
                self.log_result("Status Update Investigation", True, "Analyzed TemporalTaskManager status handling")
            else:
                self.log_result("Status Update Investigation", False, "Could not find TemporalTaskManager file")
            
            return True
            
        except Exception as e:
            self.log_result("Status Update Investigation", False, "Failed to investigate status updates", e)
            return False
    
    async def propose_solution(self):
        """Propose a solution based on findings."""
        try:
            logger.info("\n" + "=" * 60)
            logger.info("💡 PROPOSED SOLUTION")
            logger.info("=" * 60)
            
            logger.info("\n🔍 ROOT CAUSE:")
            logger.info("   1. TemporalTaskManager.submit_task() sets task status to 'submitted'")
            logger.info("   2. The workflow starts successfully and runs")
            logger.info("   3. But task status is never updated from 'submitted' to 'running'")
            logger.info("   4. API endpoint checks: has_execution_id AND status in ['running', 'pending']")
            logger.info("   5. Since status is 'submitted' (not 'running'/'pending'), API shows error")
            
            logger.info("\n🛠️  SOLUTION OPTIONS:")
            logger.info("   Option 1: Update TemporalTaskManager to set status='running' after workflow starts")
            logger.info("   Option 2: Update API endpoint to accept status='submitted' as valid")
            logger.info("   Option 3: Add background task to monitor workflow status and update task status")
            
            logger.info("\n✅ RECOMMENDED SOLUTION:")
            logger.info("   Update TemporalTaskManager.submit_task() to:")
            logger.info("   1. Start the workflow")
            logger.info("   2. Set task.execution_id = execution_id")
            logger.info("   3. Set task.status = 'running' (instead of 'submitted')")
            logger.info("   4. This will make the API endpoint work correctly")
            
            self.log_result("Solution Proposal", True, "Identified root cause and proposed solution")
            return True
            
        except Exception as e:
            self.log_result("Solution Proposal", False, "Failed to propose solution", e)
            return False
    
    async def run_debug(self):
        """Run all debug tests."""
        logger.info("🔍 Starting Task Status Transition Debug")
        logger.info("=" * 60)
        
        tests = [
            self.debug_temporal_task_manager_flow,
            self.investigate_status_update_timing,
            self.propose_solution,
        ]
        
        for test in tests:
            try:
                await test()
            except Exception as e:
                logger.error(f"Unexpected error in {test.__name__}: {e}")
            
            await asyncio.sleep(0.5)
        
        # Save results
        results_file = Path("debug_task_status_results.json")
        with open(results_file, "w") as f:
            json.dump(self.results, f, indent=2, default=str)
        
        logger.info(f"\n📄 Debug results saved to: {results_file}")

async def main():
    """Main entry point."""
    debugger = TaskStatusDebugger()
    await debugger.run_debug()

if __name__ == "__main__":
    asyncio.run(main())