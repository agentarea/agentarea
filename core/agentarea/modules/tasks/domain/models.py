"""
Task domain models for AgentArea platform.

These models represent the core task entities that enable AI agents to collaborate,
execute workflows, and integrate with MCP (Model Context Protocol) tools.
"""

from datetime import datetime, UTC
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from pydantic import BaseModel, Field

from agentarea.common.utils.types import TaskState, TaskStatus, Message, TextPart


class TaskPriority(str, Enum):
    """Task priority levels for agent workload management."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class TaskType(str, Enum):
    """Types of tasks that can be executed in the AgentArea platform."""

    # Core task types
    WORKFLOW = "workflow"  # Multi-step automated workflows
    ANALYSIS = "analysis"  # Data analysis and insights
    INTEGRATION = "integration"  # MCP tool integration tasks
    COLLABORATION = "collaboration"  # Agent-to-agent collaboration

    # Specialized task types for AgentArea use cases
    MCP_DISCOVERY = "mcp_discovery"  # Discover and configure MCP servers
    TOOL_EXECUTION = "tool_execution"  # Execute specific MCP tools
    DATA_PROCESSING = "data_processing"  # Process data across systems
    CONTENT_GENERATION = "content_generation"  # Generate content
    SYSTEM_MONITORING = "system_monitoring"  # Monitor system performance

    # Business process automation
    CUSTOMER_SUPPORT = "customer_support"
    DEVELOPMENT_ASSISTANCE = "development_assistance"
    BUSINESS_PROCESS = "business_process"


class TaskComplexity(str, Enum):
    """Task complexity levels for resource allocation."""

    SIMPLE = "simple"  # Single-step, low resource
    MODERATE = "moderate"  # Multi-step, moderate resource
    COMPLEX = "complex"  # Multi-agent, high resource
    ENTERPRISE = "enterprise"  # Large-scale, distributed


class AgentCapability(str, Enum):
    """Agent capabilities for task assignment."""

    # Core capabilities
    REASONING = "reasoning"
    ANALYSIS = "analysis"
    INTEGRATION = "integration"
    COMMUNICATION = "communication"

    # Technical capabilities
    CODE_GENERATION = "code_generation"
    DATA_PROCESSING = "data_processing"
    API_INTEGRATION = "api_integration"
    DATABASE_OPERATIONS = "database_operations"

    # Business capabilities
    CUSTOMER_SERVICE = "customer_service"
    CONTENT_CREATION = "content_creation"
    PROJECT_MANAGEMENT = "project_management"
    QUALITY_ASSURANCE = "quality_assurance"


class MCPToolReference(BaseModel):
    """Reference to an MCP tool used in task execution."""

    server_id: str
    tool_name: str
    version: Optional[str] = None
    configuration: Dict[str, Any] = Field(default_factory=dict)


class TaskDependency(BaseModel):
    """Represents a dependency between tasks."""

    task_id: str
    dependency_type: str  # "prerequisite", "parallel", "conditional"
    condition: Optional[Dict[str, Any]] = None


class TaskResource(BaseModel):
    """Resources required or allocated for task execution."""

    cpu_limit: Optional[float] = None
    memory_limit: Optional[int] = None  # MB
    timeout: Optional[int] = None  # seconds
    max_retries: Optional[int] = 3
    mcp_tools: List[MCPToolReference] = Field(default_factory=list)


class TaskMetrics(BaseModel):
    """Performance metrics for task execution."""

    execution_time: Optional[float] = None  # seconds
    cpu_usage: Optional[float] = None
    memory_usage: Optional[int] = None  # MB
    tool_calls: Optional[int] = None
    agent_switches: Optional[int] = None
    error_count: Optional[int] = None


class TaskCollaboration(BaseModel):
    """Information about agent collaboration on this task."""

    primary_agent_id: UUID
    collaborating_agents: List[UUID] = Field(default_factory=list)
    handoff_history: List[Dict[str, Any]] = Field(default_factory=list)
    collaboration_type: str = "sequential"  # "sequential", "parallel", "hierarchical"


class TaskInput(BaseModel):
    """Input requirements for task execution."""

    input_type: str
    prompt: str
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    timeout: Optional[int] = None
    required: bool = True
    provided_value: Optional[Any] = None
    provided_at: Optional[datetime] = None


class TaskArtifact(BaseModel):
    """Extended artifact model for task-specific artifacts."""

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    name: str
    content: Any
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: Optional[UUID] = None  # Agent ID
    size: Optional[int] = None  # bytes
    mime_type: Optional[str] = None


class Task(BaseModel):
    """
    Core task entity for the AgentArea platform.

    Represents a unit of work that can be executed by AI agents,
    supporting MCP tool integration and agent-to-agent collaboration.
    """

    # Core identification
    id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: Optional[str] = None
    parent_task_id: Optional[str] = None

    # Task definition
    title: str
    description: str
    task_type: TaskType
    priority: TaskPriority = TaskPriority.MEDIUM
    complexity: TaskComplexity = TaskComplexity.MODERATE

    # Agent assignment
    assigned_agent_id: Optional[UUID] = None
    required_capabilities: List[AgentCapability] = Field(default_factory=list)
    collaboration: Optional[TaskCollaboration] = None

    # Execution state
    status: TaskStatus
    parameters: Dict[str, Any] = Field(default_factory=dict)
    result: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    error_code: Optional[str] = None

    # Task relationships
    dependencies: List[TaskDependency] = Field(default_factory=list)
    subtasks: List[str] = Field(default_factory=list)  # Task IDs

    # Resources and execution
    resources: TaskResource = Field(default_factory=TaskResource)
    metrics: Optional[TaskMetrics] = None

    # Input/Output
    inputs: List[TaskInput] = Field(default_factory=list)
    artifacts: List[TaskArtifact] = Field(default_factory=list)
    history: List[Message] = Field(default_factory=list)

    # Timestamps
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Metadata
    metadata: Dict[str, Any] = Field(default_factory=dict)
    tags: List[str] = Field(default_factory=list)

    # Business context
    created_by: Optional[str] = None  # User ID
    organization_id: Optional[str] = None
    workspace_id: Optional[str] = None

    def is_pending(self) -> bool:
        """Check if task is pending execution."""
        return self.status.state == TaskState.SUBMITTED

    def is_running(self) -> bool:
        """Check if task is currently running."""
        return self.status.state == TaskState.WORKING

    def is_completed(self) -> bool:
        """Check if task is completed successfully."""
        return self.status.state == TaskState.COMPLETED

    def is_failed(self) -> bool:
        """Check if task has failed."""
        return self.status.state == TaskState.FAILED

    def is_canceled(self) -> bool:
        """Check if task was canceled."""
        return self.status.state == TaskState.CANCELED

    def requires_input(self) -> bool:
        """Check if task requires user input."""
        return self.status.state == TaskState.INPUT_REQUIRED

    def can_be_assigned(self) -> bool:
        """Check if task can be assigned to an agent."""
        return self.assigned_agent_id is None and self.is_pending()

    def add_artifact(self, artifact: TaskArtifact) -> None:
        """Add an artifact to the task."""
        self.artifacts.append(artifact)
        self.updated_at = datetime.now(UTC)

    def add_input_requirement(self, input_req: TaskInput) -> None:
        """Add an input requirement to the task."""
        self.inputs.append(input_req)
        self.updated_at = datetime.now(UTC)

    def provide_input(self, input_type: str, value: Any) -> bool:
        """Provide input for a required input type."""
        for input_req in self.inputs:
            if input_req.input_type == input_type and input_req.required:
                input_req.provided_value = value
                input_req.provided_at = datetime.now(UTC)
                self.updated_at = datetime.now(UTC)
                return True
        return False

    def get_pending_inputs(self) -> List[TaskInput]:
        """Get list of pending input requirements."""
        return [inp for inp in self.inputs if inp.required and inp.provided_value is None]

    def assign_to_agent(self, agent_id: UUID, assigned_by: Optional[str] = None) -> None:
        """Assign task to an agent."""
        self.assigned_agent_id = agent_id
        self.updated_at = datetime.now(UTC)

        if self.collaboration is None:
            self.collaboration = TaskCollaboration(primary_agent_id=agent_id)

        # Add to metadata
        self.metadata.update(
            {"assigned_at": datetime.now(UTC).isoformat(), "assigned_by": assigned_by}
        )

    def add_collaborating_agent(self, agent_id: UUID, handoff_reason: Optional[str] = None) -> None:
        """Add a collaborating agent to the task."""
        if self.collaboration is None:
            if self.assigned_agent_id:
                self.collaboration = TaskCollaboration(primary_agent_id=self.assigned_agent_id)
            else:
                self.collaboration = TaskCollaboration(primary_agent_id=agent_id)

        if agent_id not in self.collaboration.collaborating_agents:
            self.collaboration.collaborating_agents.append(agent_id)

            # Record handoff
            handoff_record = {
                "agent_id": str(agent_id),
                "timestamp": datetime.now(UTC).isoformat(),
                "reason": handoff_reason,
            }
            self.collaboration.handoff_history.append(handoff_record)
            self.updated_at = datetime.now(UTC)

    def update_status(self, new_state: TaskState, message: Optional[str] = None) -> None:
        """Update task status."""
        self.status = TaskStatus(
            state=new_state,
            message=Message(role="agent", parts=[TextPart(text=message)]) if message else None,
            timestamp=datetime.now(UTC),
        )
        self.updated_at = datetime.now(UTC)

        # Update timing
        if new_state == TaskState.WORKING and self.started_at is None:
            self.started_at = datetime.now(UTC)
        elif new_state in [TaskState.COMPLETED, TaskState.FAILED, TaskState.CANCELED]:
            self.completed_at = datetime.now(UTC)

            # Calculate execution time if we have start time
            if self.started_at and self.metrics:
                execution_time = (self.completed_at - self.started_at).total_seconds()
                self.metrics.execution_time = execution_time

    def add_mcp_tool(self, tool_ref: MCPToolReference) -> None:
        """Add an MCP tool reference to the task resources."""
        self.resources.mcp_tools.append(tool_ref)
        self.updated_at = datetime.now(UTC)

    def get_execution_summary(self) -> Dict[str, Any]:
        """Get a summary of task execution."""
        return {
            "id": self.id,
            "title": self.title,
            "type": self.task_type,
            "status": self.status.state,
            "priority": self.priority,
            "assigned_agent": str(self.assigned_agent_id) if self.assigned_agent_id else None,
            "created_at": self.created_at.isoformat(),
            "execution_time": self.metrics.execution_time if self.metrics else None,
            "artifacts_count": len(self.artifacts),
            "collaborating_agents": len(self.collaboration.collaborating_agents)
            if self.collaboration
            else 0,
            "mcp_tools_used": len(self.resources.mcp_tools),
        }


class TaskWorkflow(BaseModel):
    """
    Represents a workflow composed of multiple tasks.

    Enables complex business process automation across multiple agents and systems.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str
    version: str = "1.0.0"

    # Workflow definition
    tasks: List[str] = Field(default_factory=list)  # Task IDs in execution order
    task_definitions: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    # Execution state
    status: str = "draft"  # draft, active, paused, completed, failed
    current_task_index: int = 0

    # Configuration
    parallel_execution: bool = False
    failure_strategy: str = "stop"  # stop, continue, retry
    max_retries: int = 3

    # Metadata
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

    def add_task(self, task_definition: Dict[str, Any]) -> str:
        """Add a task to the workflow."""
        task_id = str(uuid4())
        self.tasks.append(task_id)
        self.task_definitions[task_id] = task_definition
        self.updated_at = datetime.now(UTC)
        return task_id

    def get_next_task(self) -> Optional[str]:
        """Get the next task to execute."""
        if self.current_task_index < len(self.tasks):
            return self.tasks[self.current_task_index]
        return None

    def advance_to_next_task(self) -> bool:
        """Advance to the next task in the workflow."""
        if self.current_task_index < len(self.tasks) - 1:
            self.current_task_index += 1
            self.updated_at = datetime.now(UTC)
            return True
        return False


class TaskTemplate(BaseModel):
    """
    Template for creating standardized tasks.

    Enables reusable task patterns for common AgentArea workflows.
    """

    id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str
    category: str  # "integration", "analysis", "automation", etc.

    # Template definition
    task_type: TaskType
    priority: TaskPriority = TaskPriority.MEDIUM
    complexity: TaskComplexity = TaskComplexity.MODERATE
    required_capabilities: List[AgentCapability] = Field(default_factory=list)

    # Default configuration
    default_parameters: Dict[str, Any] = Field(default_factory=dict)
    parameter_schema: Dict[str, Any] = Field(default_factory=dict)
    default_resources: TaskResource = Field(default_factory=TaskResource)

    # Template metadata
    version: str = "1.0.0"
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    created_by: Optional[str] = None
    tags: List[str] = Field(default_factory=list)

    def create_task(
        self, title: str, description: str, parameters: Optional[Dict[str, Any]] = None
    ) -> Task:
        """Create a task instance from this template."""
        task_params = self.default_parameters.copy()
        if parameters:
            task_params.update(parameters)

        return Task(
            title=title,
            description=description,
            task_type=self.task_type,
            priority=self.priority,
            complexity=self.complexity,
            required_capabilities=self.required_capabilities.copy(),
            parameters=task_params,
            resources=self.default_resources.model_copy(),
            tags=self.tags.copy(),
            metadata={"created_from_template": self.id},
            status=TaskStatus(state=TaskState.SUBMITTED, timestamp=datetime.now(UTC)),
        )
