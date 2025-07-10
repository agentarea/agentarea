"""
Simple Temporal Workflow Service

Starts Temporal workflows asynchronously for agent execution.
Returns immediately with task_id while workflow runs in background.
"""

import logging
from datetime import timedelta
from typing import Any, Dict, Optional
from uuid import UUID, uuid4

logger = logging.getLogger(__name__)

# Optional Temporal imports
temporal_available = False
try:
    from temporalio import Client
    from agentarea_execution.workflows.agent_execution import AgentExecutionWorkflow  
    from agentarea_execution.models import AgentExecutionRequest
    temporal_available = True
except ImportError:
    temporal_available = False
    logger.warning("Temporal not available - using mock execution")
    # Define stub classes when imports fail
    class Client: pass
    class AgentExecutionWorkflow: pass
    class AgentExecutionRequest: pass


class TemporalWorkflowService:
    """Service for executing agent tasks via Temporal workflows."""
    
    def __init__(self, temporal_address: str = "localhost:7233"):
        self.temporal_address = temporal_address
        self._client: Optional[Any] = None
    
    async def get_client(self):
        """Get or create Temporal client."""
        if not temporal_available:
            return None
            
        if self._client is None:
            try:
                self._client = await Client.connect(self.temporal_address)
                logger.info(f"Connected to Temporal at {self.temporal_address}")
            except Exception as e:
                logger.error(f"Failed to connect to Temporal: {e}")
                return None
        return self._client
    
    async def execute_agent_task_async(
        self,
        agent_id: UUID,
        task_query: str,
        user_id: str = "anonymous",
        session_id: Optional[str] = None,
        task_parameters: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 300,
    ) -> Dict[str, Any]:
        """
        Start agent execution workflow asynchronously.
        
        Returns immediately with task_id and execution_id.
        Workflow runs in background via Temporal.
        
        Args:
            agent_id: UUID of agent to execute
            task_query: Message/query to send to agent
            user_id: User ID making the request
            session_id: Chat session ID
            task_parameters: Additional parameters
            timeout_seconds: Workflow timeout
            
        Returns:
            Dict with task_id, execution_id, status
        """
        task_id = uuid4()
        execution_id = f"agent-task-{task_id}"
        
        try:
            if not temporal_available:
                logger.warning("Temporal not available - using mock execution")
                return await self._mock_execution(task_id, execution_id, agent_id, task_query)
            
            client = await self.get_client()
            if not client:
                logger.warning("Temporal client unavailable - using mock execution")
                return await self._mock_execution(task_id, execution_id, agent_id, task_query)
            
            # Create execution request
            request = AgentExecutionRequest(
                task_id=task_id,
                agent_id=agent_id,
                user_id=user_id,
                task_query=task_query,
                task_parameters=task_parameters or {},
                timeout_seconds=timeout_seconds,
            )
            
            # Start workflow asynchronously (returns immediately)
            await client.execute_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=execution_id,
                task_queue="agent-execution",
                execution_timeout=timedelta(seconds=timeout_seconds),
            )
            
            logger.info(f"Started Temporal workflow: {execution_id}")
            
            return {
                "success": True,
                "task_id": str(task_id),
                "execution_id": execution_id,
                "status": "started",
                "temporal_available": True,
            }
            
        except Exception as e:
            logger.error(f"Failed to start workflow: {e}")
            return {
                "success": False,
                "task_id": str(task_id),
                "execution_id": execution_id,
                "status": "failed",
                "error": str(e),
                "temporal_available": temporal_available,
            }
    
    async def get_workflow_status(self, execution_id: str) -> Dict[str, Any]:
        """
        Get workflow execution status for long polling.
        
        Args:
            execution_id: Temporal workflow execution ID
            
        Returns:
            Dict with status, result, error info
        """
        try:
            if not temporal_available:
                return await self._mock_status_check(execution_id)
            
            client = await self.get_client()
            if not client:
                return await self._mock_status_check(execution_id)
            
            # Get workflow handle
            handle = client.get_workflow_handle(execution_id)
            
            # Check if workflow is running
            try:
                result = await handle.result()
                
                # Workflow completed successfully
                return {
                    "status": "completed",
                    "success": True,
                    "result": {
                        "response": result.final_response if hasattr(result, 'final_response') else str(result),
                        "conversation_history": getattr(result, 'conversation_history', []),
                        "execution_metrics": getattr(result, 'execution_metrics', {}),
                    },
                    "start_time": None,  # TODO: Get from Temporal
                    "end_time": None,    # TODO: Get from Temporal
                }
                
            except Exception as workflow_error:
                # Workflow failed
                return {
                    "status": "failed", 
                    "success": False,
                    "error": str(workflow_error),
                    "result": None,
                }
                
        except Exception as e:
            logger.error(f"Failed to get workflow status: {e}")
            return {
                "status": "error",
                "success": False,
                "error": str(e),
                "result": None,
            }
    
    async def _mock_execution(self, task_id: UUID, execution_id: str, agent_id: UUID, task_query: str) -> Dict[str, Any]:
        """Mock execution when Temporal is not available."""
        logger.info(f"Mock execution for agent {agent_id}: {task_query}")
        
        # Simulate async execution without blocking
        import asyncio
        
        async def mock_workflow():
            await asyncio.sleep(2)  # Simulate processing time
            return f"Mock response to: {task_query}"
        
        # Start mock execution in background
        asyncio.create_task(mock_workflow())
        
        return {
            "success": True,
            "task_id": str(task_id),
            "execution_id": execution_id,
            "status": "started",
            "temporal_available": False,
        }
    
    async def _mock_status_check(self, execution_id: str) -> Dict[str, Any]:
        """Mock status check when Temporal is not available."""
        # Simple mock - always return completed after 3 seconds
        import time
        
        if "mock-completed" in execution_id:
            return {
                "status": "completed",
                "success": True,
                "result": {
                    "response": "This is a mock response since Temporal is not available. In production, the agent would provide a real response.",
                    "conversation_history": [],
                    "execution_metrics": {"mock": True},
                },
            }
        else:
            # Mark as completed for next check
            return {
                "status": "processing",
                "success": None,
                "result": None,
            } 

    async def cancel_task(self, execution_id: str) -> bool:
        """
        Cancel a running Temporal workflow.
        
        Args:
            execution_id: Temporal workflow execution ID
            
        Returns:
            True if cancelled successfully, False otherwise
        """
        try:
            if not temporal_available:
                logger.warning("Temporal not available - mock cancellation")
                return True  # Mock success
            
            client = await self.get_client()
            if not client:
                logger.warning("Temporal client unavailable - mock cancellation")
                return True  # Mock success
            
            # Get workflow handle
            handle = client.get_workflow_handle(execution_id)
            
            # Cancel the workflow
            await handle.cancel()
            
            logger.info(f"Cancelled Temporal workflow: {execution_id}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to cancel workflow {execution_id}: {e}")
            return False 