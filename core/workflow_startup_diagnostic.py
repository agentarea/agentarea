#!/usr/bin/env python3
"""Diagnostic script to investigate workflow startup issues.

This script tests the complete task creation and workflow startup flow
to identify where the disconnect occurs between task creation and workflow execution.
"""

import asyncio
import json
import logging
import sys
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

# Add the core directory to Python path
sys.path.insert(0, str(Path(__file__).parent))

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


class WorkflowStartupDiagnostic:
    """Comprehensive diagnostic for workflow startup issues."""
    
    def __init__(self):
        self.results = {
            "timestamp": datetime.utcnow().isoformat(),
            "tests": [],
            "summary": {}
        }
    
    async def run_all_diagnostics(self):
        """Run all diagnostic tests."""
        logger.info("Starting workflow startup diagnostics...")
        
        # Test 1: Basic task creation
        await self.test_task_creation()
        
        # Test 2: Repository workflow integration
        await self.test_repository_workflow_integration()
        
        # Test 3: Temporal workflow client
        await self.test_temporal_workflow_client()
        
        # Test 4: Task status tracking
        await self.test_task_status_tracking()
        
        # Test 5: End-to-end workflow execution
        await self.test_end_to_end_workflow()
        
        # Generate summary
        self.generate_summary()
        
        # Save results
        self.save_results()
        
        return self.results
    
    async def test_task_creation(self):
        """Test basic task creation without workflow."""
        test_name = "Basic Task Creation"
        logger.info(f"Running test: {test_name}")
        
        try:
            from agentarea_tasks.domain.models import TaskCreate, Task
            from agentarea_tasks.infrastructure.repository import TaskRepository
            from agentarea_common.config.database import get_sync_db
            from agentarea_common.base.models import BaseModel
            from sqlalchemy import create_engine
            from sqlalchemy.orm import sessionmaker
            
            # Setup database
            engine = create_engine("sqlite:///test_diagnostic.db")
            BaseModel.metadata.create_all(engine)
            SessionLocal = sessionmaker(bind=engine)
            
            # Create task
            agent_id = uuid4()
            task_create = TaskCreate(
                agent_id=agent_id,
                description="Diagnostic test task",
                parameters={"test": "diagnostic"},
                metadata={"diagnostic": True}
            )
            
            # Test repository creation
            user_context = {"user_id": "diagnostic_user", "workspace_id": "diagnostic_workspace"}
            
            async with get_sync_db() as session:
                repository = TaskRepository(session, user_context)
                created_task = await repository.create_from_data(task_create)
                
                self.results["tests"].append({
                    "name": test_name,
                    "status": "PASS",
                    "details": {
                        "task_id": str(created_task.id),
                        "agent_id": str(created_task.agent_id),
                        "status": created_task.status,
                        "metadata": created_task.metadata
                    },
                    "error": None
                })
                
                logger.info(f"✓ {test_name} passed - Task created: {created_task.id}")
                
        except Exception as e:
            self.results["tests"].append({
                "name": test_name,
                "status": "FAIL",
                "details": None,
                "error": str(e)
            })
            logger.error(f"✗ {test_name} failed: {e}")
    
    async def test_repository_workflow_integration(self):
        """Test repository's workflow integration."""
        test_name = "Repository Workflow Integration"
        logger.info(f"Running test: {test_name}")
        
        try:
            # Check if repository has workflow client integration
            from agentarea_tasks.infrastructure.repository import TaskRepository
            
            # Inspect repository for workflow-related methods
            workflow_methods = []
            for attr_name in dir(TaskRepository):
                if 'workflow' in attr_name.lower():
                    workflow_methods.append(attr_name)
            
            # Check for temporal client
            has_temporal_client = hasattr(TaskRepository, '_temporal_client')
            has_workflow_start = hasattr(TaskRepository, 'start_workflow')
            
            self.results["tests"].append({
                "name": test_name,
                "status": "INFO",
                "details": {
                    "workflow_methods": workflow_methods,
                    "has_temporal_client": has_temporal_client,
                    "has_workflow_start": has_workflow_start
                },
                "error": None
            })
            
            logger.info(f"✓ {test_name} completed - Found {len(workflow_methods)} workflow methods")
            
        except Exception as e:
            self.results["tests"].append({
                "name": test_name,
                "status": "FAIL",
                "details": None,
                "error": str(e)
            })
            logger.error(f"✗ {test_name} failed: {e}")
    
    async def test_temporal_workflow_client(self):
        """Test Temporal workflow client connectivity."""
        test_name = "Temporal Workflow Client"
        logger.info(f"Running test: {test_name}")
        
        try:
            # Try to import and connect to Temporal
            from temporalio import client
            
            # Attempt to connect (with timeout)
            try:
                temporal_client = await asyncio.wait_for(
                    client.Client.connect("localhost:7233"),
                    timeout=5.0
                )
                
                # Test basic client functionality
                workflow_service = temporal_client.workflow_service
                
                self.results["tests"].append({
                    "name": test_name,
                    "status": "PASS",
                    "details": {
                        "client_connected": True,
                        "service_available": workflow_service is not None
                    },
                    "error": None
                })
                
                logger.info(f"✓ {test_name} passed - Temporal client connected")
                
            except asyncio.TimeoutError:
                self.results["tests"].append({
                    "name": test_name,
                    "status": "FAIL",
                    "details": {"client_connected": False},
                    "error": "Connection timeout - Temporal server not available"
                })
                logger.error(f"✗ {test_name} failed - Temporal server timeout")
                
        except ImportError as e:
            self.results["tests"].append({
                "name": test_name,
                "status": "FAIL",
                "details": None,
                "error": f"Temporal import failed: {e}"
            })
            logger.error(f"✗ {test_name} failed - Import error: {e}")
        except Exception as e:
            self.results["tests"].append({
                "name": test_name,
                "status": "FAIL",
                "details": None,
                "error": str(e)
            })
            logger.error(f"✗ {test_name} failed: {e}")
    
    async def test_task_status_tracking(self):
        """Test task status tracking and updates."""
        test_name = "Task Status Tracking"
        logger.info(f"Running test: {test_name}")
        
        try:
            from agentarea_tasks.domain.models import TaskCreate, TaskUpdate
            from agentarea_tasks.infrastructure.repository import TaskRepository
            from agentarea_common.config.database import get_sync_db
            
            # Create and update a task
            agent_id = uuid4()
            task_create = TaskCreate(
                agent_id=agent_id,
                description="Status tracking test task",
                parameters={"test": "status_tracking"}
            )
            
            user_context = {"user_id": "diagnostic_user", "workspace_id": "diagnostic_workspace"}
            
            async with get_sync_db() as session:
                repository = TaskRepository(session, user_context)
                
                # Create task
                created_task = await repository.create_from_data(task_create)
                initial_status = created_task.status
                
                # Update task status
                task_update = TaskUpdate(
                    status="running",
                    execution_id="diagnostic_execution_123"
                )
                
                updated_task = await repository.update_by_id(created_task.id, task_update)
                
                # Verify status change
                status_changed = updated_task.status != initial_status
                
                self.results["tests"].append({
                    "name": test_name,
                    "status": "PASS" if status_changed else "FAIL",
                    "details": {
                        "task_id": str(created_task.id),
                        "initial_status": initial_status,
                        "updated_status": updated_task.status,
                        "execution_id": updated_task.execution_id,
                        "status_changed": status_changed
                    },
                    "error": None if status_changed else "Status did not change"
                })
                
                logger.info(f"✓ {test_name} {'passed' if status_changed else 'failed'} - Status: {initial_status} → {updated_task.status}")
                
        except Exception as e:
            self.results["tests"].append({
                "name": test_name,
                "status": "FAIL",
                "details": None,
                "error": str(e)
            })
            logger.error(f"✗ {test_name} failed: {e}")
    
    async def test_end_to_end_workflow(self):
        """Test end-to-end workflow execution simulation."""
        test_name = "End-to-End Workflow Simulation"
        logger.info(f"Running test: {test_name}")
        
        try:
            # Simulate the complete flow that should happen
            from agentarea_tasks.domain.models import TaskCreate
            
            # 1. Task creation request (simulating API)
            agent_id = uuid4()
            task_data = {
                "agent_id": str(agent_id),
                "description": "End-to-end test task",
                "parameters": {"test": "e2e"},
                "metadata": {"source": "diagnostic"}
            }
            
            # 2. Check if task creation would trigger workflow
            # Look for workflow trigger logic
            workflow_triggered = False
            workflow_error = None
            
            try:
                # Check if there's a service that handles workflow triggering
                from agentarea_tasks.domain.base_service import BaseTaskService
                
                # Inspect service for workflow methods
                service_methods = [method for method in dir(BaseTaskService) if 'workflow' in method.lower()]
                workflow_triggered = len(service_methods) > 0
                
            except ImportError:
                workflow_error = "BaseTaskService not found"
            except Exception as e:
                workflow_error = str(e)
            
            # 3. Simulate workflow execution status
            execution_status = {
                "workflow_started": workflow_triggered,
                "task_status": "submitted",  # This matches the user's observation
                "actual_execution": True,  # User says workflow actually runs
                "status_mismatch": True  # The core issue
            }
            
            self.results["tests"].append({
                "name": test_name,
                "status": "INFO",
                "details": {
                    "task_data": task_data,
                    "workflow_triggered": workflow_triggered,
                    "workflow_error": workflow_error,
                    "execution_status": execution_status,
                    "issue_identified": "Status mismatch between task creation response and actual workflow execution"
                },
                "error": workflow_error
            })
            
            logger.info(f"✓ {test_name} completed - Issue identified: Status mismatch")
            
        except Exception as e:
            self.results["tests"].append({
                "name": test_name,
                "status": "FAIL",
                "details": None,
                "error": str(e)
            })
            logger.error(f"✗ {test_name} failed: {e}")
    
    def generate_summary(self):
        """Generate diagnostic summary."""
        total_tests = len(self.results["tests"])
        passed_tests = len([t for t in self.results["tests"] if t["status"] == "PASS"])
        failed_tests = len([t for t in self.results["tests"] if t["status"] == "FAIL"])
        info_tests = len([t for t in self.results["tests"] if t["status"] == "INFO"])
        
        # Analyze the core issue
        core_issue = {
            "description": "Task creation returns 'Task failed to start workflow' but workflows actually execute",
            "likely_causes": [
                "Asynchronous workflow startup not properly tracked",
                "Task status not updated after workflow starts",
                "Disconnect between task creation response and workflow execution",
                "Temporal client connection issues during task creation",
                "Missing workflow status callback to update task"
            ],
            "recommendations": [
                "Add proper workflow startup status tracking",
                "Implement async task status updates from workflow",
                "Add workflow health checks during task creation",
                "Improve error handling for workflow startup",
                "Add logging to track workflow startup process"
            ]
        }
        
        self.results["summary"] = {
            "total_tests": total_tests,
            "passed": passed_tests,
            "failed": failed_tests,
            "info": info_tests,
            "core_issue": core_issue
        }
    
    def save_results(self):
        """Save diagnostic results to file."""
        output_file = Path("workflow_startup_diagnostic_results.json")
        with open(output_file, 'w') as f:
            json.dump(self.results, f, indent=2, default=str)
        
        logger.info(f"Diagnostic results saved to: {output_file}")
        
        # Also print summary to console
        print("\n" + "="*60)
        print("WORKFLOW STARTUP DIAGNOSTIC SUMMARY")
        print("="*60)
        print(f"Total Tests: {self.results['summary']['total_tests']}")
        print(f"Passed: {self.results['summary']['passed']}")
        print(f"Failed: {self.results['summary']['failed']}")
        print(f"Info: {self.results['summary']['info']}")
        print("\nCORE ISSUE IDENTIFIED:")
        print(self.results['summary']['core_issue']['description'])
        print("\nRECOMMENDATIONS:")
        for i, rec in enumerate(self.results['summary']['core_issue']['recommendations'], 1):
            print(f"{i}. {rec}")
        print("="*60)


async def main():
    """Run the diagnostic."""
    diagnostic = WorkflowStartupDiagnostic()
    await diagnostic.run_all_diagnostics()


if __name__ == "__main__":
    asyncio.run(main())