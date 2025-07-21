"""Domain interfaces for agent execution."""

from abc import ABC, abstractmethod
from typing import Any, Dict, Optional
from uuid import UUID


class ExecutionRequest:
    """Value object for execution requests."""
    
    def __init__(
        self,
        agent_id: UUID,
        task_query: str,
        user_id: str = "anonymous",
        session_id: Optional[str] = None,
        task_parameters: Optional[Dict[str, Any]] = None,
        timeout_seconds: int = 300,
    ):
        self.agent_id = agent_id
        self.task_query = task_query
        self.user_id = user_id
        self.session_id = session_id
        self.task_parameters = task_parameters or {}
        self.timeout_seconds = timeout_seconds


class ExecutionResult:
    """Value object for execution results."""
    
    def __init__(
        self,
        task_id: str,
        execution_id: str,
        success: bool,
        status: str,
        content: Optional[str] = None,
        error: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ):
        self.task_id = task_id
        self.execution_id = execution_id
        self.success = success
        self.status = status
        self.content = content
        self.error = error
        self.metadata = metadata or {}


class ExecutionServiceInterface(ABC):
    """Interface for agent execution services."""
    
    @abstractmethod
    async def execute_async(self, request: ExecutionRequest) -> ExecutionResult:
        """Execute agent task asynchronously."""
        pass
    
    @abstractmethod
    async def get_status(self, execution_id: str) -> Dict[str, Any]:
        """Get execution status."""
        pass
    
    @abstractmethod
    async def cancel_execution(self, execution_id: str) -> bool:
        """Cancel execution."""
        pass
    
    @abstractmethod
    async def pause_execution(self, execution_id: str) -> bool:
        """Pause execution."""
        pass
    
    @abstractmethod
    async def resume_execution(self, execution_id: str) -> bool:
        """Resume execution."""
        pass


class WorkflowServiceInterface(ABC):
    """Interface for workflow orchestration."""
    
    @abstractmethod
    async def start_workflow(self, request: ExecutionRequest) -> ExecutionResult:
        """Start a workflow execution."""
        pass
    
    @abstractmethod
    async def get_workflow_status(self, execution_id: str) -> Dict[str, Any]:
        """Get workflow status."""
        pass 