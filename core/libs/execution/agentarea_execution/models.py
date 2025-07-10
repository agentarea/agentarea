"""
Domain models for agent execution workflows.

Integrates with existing AgentArea domain models and uses proper UUID types.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from uuid import UUID


@dataclass
class AgentExecutionRequest:
    """Request to execute an agent task via Temporal workflow."""
    
    # Core identification
    task_id: UUID
    agent_id: UUID
    user_id: str
    
    # Task content
    task_query: str
    task_parameters: Dict[str, Any] = field(default_factory=dict)
    
    # Execution configuration
    timeout_seconds: int = 300
    max_reasoning_iterations: int = 10
    enable_agent_communication: bool = False
    
    # Additional workflow metadata
    workflow_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AgentExecutionResult:
    """Result of agent execution workflow."""
    
    # Core identification
    task_id: UUID
    agent_id: UUID
    
    # Execution results
    success: bool
    final_response: Optional[str] = None
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Performance metrics
    reasoning_iterations_used: int = 0
    total_tool_calls: int = 0
    execution_duration_seconds: Optional[float] = None
    
    # Error handling
    error_message: Optional[str] = None
    
    # Artifacts and outputs
    artifacts: List[Dict[str, Any]] = field(default_factory=list)
    agent_memory_updates: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ToolExecutionRequest:
    """Request to execute a tool via MCP server."""
    
    # Tool identification
    tool_name: str
    tool_server_id: UUID  # MCP server instance ID
    
    # Tool parameters
    arguments: Dict[str, Any]
    
    # Execution context
    agent_id: UUID
    task_id: UUID
    user_id: str
    
    # Timeout configuration
    timeout_seconds: int = 60


@dataclass
class ToolExecutionResult:
    """Result of tool execution."""
    
    # Core identification
    tool_name: str
    tool_server_id: UUID
    
    # Execution results
    success: bool
    output: Optional[str] = None
    error_message: Optional[str] = None
    
    # Metadata
    execution_time_seconds: Optional[float] = None
    server_metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMReasoningRequest:
    """Request for LLM reasoning and tool selection."""
    
    # Agent context
    agent_id: UUID
    task_id: UUID
    
    # Conversation context
    conversation_history: List[Dict[str, Any]]
    current_goal: str
    
    # Available tools
    available_tools: List[Dict[str, Any]]
    
    # Reasoning constraints
    max_tool_calls: int = 5
    include_thinking: bool = True


@dataclass
class LLMReasoningResult:
    """Result of LLM reasoning."""
    
    # Core response
    reasoning_text: str
    tool_calls: List[Dict[str, Any]]
    
    # Metadata
    model_used: str
    reasoning_time_seconds: Optional[float] = None
    
    # Completion indicators
    believes_task_complete: bool = False
    completion_confidence: float = 0.0

    def __post_init__(self):
        if not self.tool_calls:
            self.tool_calls = [] 