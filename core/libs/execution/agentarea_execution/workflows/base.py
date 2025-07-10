"""
Base workflow interfaces for AgentArea execution system.

These base classes define the common patterns and interfaces for Temporal workflows
in the AgentArea platform, following best practices for durable execution.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, TypeVar, Generic
from uuid import UUID

# from ..domain.models import Task, Workflow, Agent, ExecutionContext

T = TypeVar('T')


@dataclass
class WorkflowContext:
    """Context passed to workflow executions."""
    workflow_id: UUID
    execution_id: str
    run_id: str
    task_queue: str
    namespace: str = "default"
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    metadata: Dict[str, Any] = field(default_factory=dict)
    shared_state: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ActivityContext:
    """Context for activity executions."""
    activity_id: str
    workflow_context: WorkflowContext
    task_token: str
    attempt: int = 1
    heartbeat_timeout: Optional[timedelta] = None
    schedule_to_close_timeout: Optional[timedelta] = None
    metadata: Dict[str, Any] = field(default_factory=dict)


class WorkflowActivity(ABC):
    """Base class for workflow activities."""
    
    @abstractmethod
    async def execute(self, context: ActivityContext, **kwargs: Any) -> Any:
        """Execute the activity with the given context and parameters."""
        pass
    
    @abstractmethod
    def get_name(self) -> str:
        """Get the activity name for registration."""
        pass
    
    def get_options(self) -> Dict[str, Any]:
        """Get activity options (timeouts, retry policies, etc.)."""
        return {
            "start_to_close_timeout": timedelta(minutes=5),
            "heartbeat_timeout": timedelta(minutes=1),
            "retry_policy": {
                "initial_interval": timedelta(seconds=1),
                "backoff_coefficient": 2.0,
                "maximum_interval": timedelta(minutes=1),
                "maximum_attempts": 3,
            }
        }


class BaseWorkflow(ABC, Generic[T]):
    """Base class for all AgentArea workflows."""
    
    @abstractmethod
    async def run(self, context: WorkflowContext, **kwargs: Any) -> T:
        """Main workflow execution method."""
        pass
    
    @abstractmethod
    def get_workflow_id(self) -> str:
        """Get unique workflow identifier."""
        pass
    
    def get_workflow_options(self) -> Dict[str, Any]:
        """Get workflow options (timeouts, retry policies, etc.)."""
        return {
            "execution_timeout": timedelta(hours=24),
            "run_timeout": timedelta(hours=24),
            "task_timeout": timedelta(minutes=10),
            "retry_policy": {
                "initial_interval": timedelta(seconds=1),
                "backoff_coefficient": 2.0,
                "maximum_interval": timedelta(minutes=1),
                "maximum_attempts": 3,
            }
        }
    
    async def signal_handler(self, signal_name: str, data: Any) -> None:
        """Handle workflow signals."""
        pass
    
    async def query_handler(self, query_name: str, **kwargs: Any) -> Any:
        """Handle workflow queries."""
        pass


class StatefulWorkflow(BaseWorkflow[T]):
    """Base class for workflows that maintain state across activities."""
    
    def __init__(self):
        self._state: Dict[str, Any] = {}
        self._execution_history: List[str] = []
    
    def get_state(self, key: str, default: Any = None) -> Any:
        """Get workflow state value."""
        return self._state.get(key, default)
    
    def set_state(self, key: str, value: Any) -> None:
        """Set workflow state value."""
        self._state[key] = value
        self._execution_history.append(f"State updated: {key}")
    
    def get_execution_history(self) -> List[str]:
        """Get workflow execution history."""
        return self._execution_history.copy()
    
    def add_history_entry(self, entry: str) -> None:
        """Add entry to execution history."""
        self._execution_history.append(f"{datetime.now(timezone.utc).isoformat()}: {entry}")


class LongRunningWorkflow(StatefulWorkflow[T]):
    """Base class for long-running workflows that may span days/weeks."""
    
    def get_workflow_options(self) -> Dict[str, Any]:
        """Get workflow options optimized for long-running workflows."""
        options = super().get_workflow_options()
        options.update({
            "execution_timeout": timedelta(days=30),
            "run_timeout": timedelta(days=30),
            "task_timeout": timedelta(hours=1),
        })
        return options
    
    async def checkpoint(self, checkpoint_name: str) -> None:
        """Create a checkpoint in the workflow execution."""
        self.add_history_entry(f"Checkpoint: {checkpoint_name}")
        self.set_state("last_checkpoint", checkpoint_name)
        self.set_state("last_checkpoint_time", datetime.now(timezone.utc).isoformat())
    
    async def wait_for_signal(self, signal_name: str, timeout: Optional[timedelta] = None) -> Any:
        """Wait for a specific signal with optional timeout."""
        # Implementation would use Temporal's await_workflow_signal
        pass
    
    async def sleep_until(self, target_time: datetime) -> None:
        """Sleep until a specific time."""
        # Implementation would use Temporal's workflow.sleep
        pass 