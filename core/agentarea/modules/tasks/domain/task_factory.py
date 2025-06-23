"""
Task factory for creating and managing tasks in AgentArea.

This factory provides convenient methods for creating common task types
and ensures proper integration with the event system for agent execution.
"""

from datetime import datetime, UTC
from typing import Any, Dict, List, Optional
from uuid import UUID

from agentarea.modules.tasks.domain.models import (
    Task,
    TaskType,
    TaskPriority,
    TaskComplexity,
    AgentCapability,
    TaskTemplate,
    MCPToolReference,
    TaskResource,
)
from agentarea.common.utils.types import TaskState, TaskStatus


class TaskFactory:
    """Factory for creating standardized tasks."""

    @staticmethod
    def create_simple_task(
        title: str,
        description: str,
        agent_id: Optional[UUID] = None,
        priority: TaskPriority = TaskPriority.MEDIUM,
        task_type: TaskType = TaskType.ANALYSIS,
        parameters: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Task:
        """Create a simple task ready for agent execution."""

        task = Task(
            title=title,
            description=description,
            task_type=task_type,
            priority=priority,
            complexity=TaskComplexity.SIMPLE,
            status=TaskStatus(state=TaskState.SUBMITTED, timestamp=datetime.now(UTC)),
            parameters=parameters or {},
            metadata=metadata or {},
        )

        if agent_id:
            task.assign_to_agent(agent_id, "task_factory")

        return task

    @staticmethod
    def create_mcp_integration_task(
        title: str,
        description: str,
        mcp_server_id: str,
        tool_name: str,
        agent_id: Optional[UUID] = None,
        tool_configuration: Optional[Dict[str, Any]] = None,
        priority: TaskPriority = TaskPriority.MEDIUM,
    ) -> Task:
        """Create a task for MCP tool integration."""

        mcp_tool = MCPToolReference(
            server_id=mcp_server_id, tool_name=tool_name, configuration=tool_configuration or {}
        )

        task = Task(
            title=title,
            description=description,
            task_type=TaskType.MCP_DISCOVERY,
            priority=priority,
            complexity=TaskComplexity.MODERATE,
            required_capabilities=[AgentCapability.INTEGRATION, AgentCapability.API_INTEGRATION],
            status=TaskStatus(state=TaskState.SUBMITTED, timestamp=datetime.now(UTC)),
            resources=TaskResource(mcp_tools=[mcp_tool]),
            metadata={
                "mcp_server_id": mcp_server_id,
                "tool_name": tool_name,
                "task_category": "mcp_integration",
            },
        )

        if agent_id:
            task.assign_to_agent(agent_id, "task_factory")

        return task

    @staticmethod
    def create_test_task(agent_id: UUID) -> Task:
        """Create a simple test task for agent execution testing."""

        task = Task(
            title="Тест агента",
            description="Простая задача для тестирования работы агента. Агент должен ответить 'Задача выполнена успешно!'",
            task_type=TaskType.ANALYSIS,
            priority=TaskPriority.LOW,
            complexity=TaskComplexity.SIMPLE,
            required_capabilities=[AgentCapability.REASONING],
            status=TaskStatus(state=TaskState.SUBMITTED, timestamp=datetime.now(UTC)),
            parameters={"expected_response": "Задача выполнена успешно!", "test_mode": True},
            metadata={
                "task_category": "test",
                "auto_created": True,
                "creation_source": "task_factory",
            },
        )

        task.assign_to_agent(agent_id, "task_factory")
        return task

    @staticmethod
    def create_collaboration_task(
        title: str,
        description: str,
        primary_agent_id: UUID,
        collaborating_agents: List[UUID],
        priority: TaskPriority = TaskPriority.HIGH,
    ) -> Task:
        """Create a task that requires multiple agents to collaborate."""

        task = Task(
            title=title,
            description=description,
            task_type=TaskType.COLLABORATION,
            priority=priority,
            complexity=TaskComplexity.COMPLEX,
            required_capabilities=[
                AgentCapability.REASONING,
                AgentCapability.COMMUNICATION,
                AgentCapability.PROJECT_MANAGEMENT,
            ],
            status=TaskStatus(state=TaskState.SUBMITTED, timestamp=datetime.now(UTC)),
            metadata={
                "collaboration_required": True,
                "estimated_agents": len(collaborating_agents) + 1,
            },
        )

        task.assign_to_agent(primary_agent_id, "task_factory")

        # Add collaborating agents
        for agent_id in collaborating_agents:
            task.add_collaborating_agent(agent_id, "initial_collaboration_setup")

        return task

    @staticmethod
    def create_workflow_task(
        title: str,
        description: str,
        steps: List[Dict[str, Any]],
        agent_id: Optional[UUID] = None,
        priority: TaskPriority = TaskPriority.MEDIUM,
    ) -> Task:
        """Create a workflow task with multiple steps."""

        task = Task(
            title=title,
            description=description,
            task_type=TaskType.WORKFLOW,
            priority=priority,
            complexity=TaskComplexity.COMPLEX,
            required_capabilities=[AgentCapability.REASONING, AgentCapability.PROJECT_MANAGEMENT],
            status=TaskStatus(state=TaskState.SUBMITTED, timestamp=datetime.now(UTC)),
            parameters={"workflow_steps": steps, "current_step": 0, "total_steps": len(steps)},
            metadata={
                "task_category": "workflow",
                "steps_count": len(steps),
                "workflow_type": "sequential",
            },
        )

        if agent_id:
            task.assign_to_agent(agent_id, "task_factory")

        return task


# Pre-defined task templates for common AgentArea use cases
class CommonTaskTemplates:
    """Pre-defined templates for common AgentArea tasks."""

    @staticmethod
    def get_data_analysis_template() -> TaskTemplate:
        """Template for data analysis tasks."""
        return TaskTemplate(
            name="Data Analysis Task",
            description="Analyze data and provide insights",
            category="analysis",
            task_type=TaskType.DATA_PROCESSING,
            priority=TaskPriority.MEDIUM,
            complexity=TaskComplexity.MODERATE,
            required_capabilities=[
                AgentCapability.ANALYSIS,
                AgentCapability.DATA_PROCESSING,
                AgentCapability.REASONING,
            ],
            default_parameters={
                "analysis_type": "descriptive",
                "output_format": "report",
                "include_visualizations": True,
            },
            parameter_schema={
                "data_source": {"type": "string", "required": True},
                "analysis_type": {
                    "type": "string",
                    "enum": ["descriptive", "predictive", "diagnostic"],
                },
                "output_format": {"type": "string", "enum": ["report", "dashboard", "json"]},
            },
            tags=["analytics", "data", "insights"],
        )

    @staticmethod
    def get_customer_support_template() -> TaskTemplate:
        """Template for customer support tasks."""
        return TaskTemplate(
            name="Customer Support Task",
            description="Handle customer inquiries and provide support",
            category="customer_service",
            task_type=TaskType.CUSTOMER_SUPPORT,
            priority=TaskPriority.HIGH,
            complexity=TaskComplexity.MODERATE,
            required_capabilities=[
                AgentCapability.CUSTOMER_SERVICE,
                AgentCapability.COMMUNICATION,
                AgentCapability.REASONING,
            ],
            default_parameters={
                "response_time_limit": 300,  # 5 minutes
                "escalation_threshold": 2,
                "sentiment_analysis": True,
            },
            parameter_schema={
                "customer_id": {"type": "string", "required": True},
                "inquiry_type": {"type": "string", "enum": ["technical", "billing", "general"]},
                "priority": {"type": "string", "enum": ["low", "medium", "high", "urgent"]},
            },
            tags=["support", "customer", "service"],
        )

    @staticmethod
    def get_mcp_integration_template() -> TaskTemplate:
        """Template for MCP integration tasks."""
        return TaskTemplate(
            name="MCP Integration Task",
            description="Integrate with MCP servers and tools",
            category="integration",
            task_type=TaskType.MCP_DISCOVERY,
            priority=TaskPriority.MEDIUM,
            complexity=TaskComplexity.MODERATE,
            required_capabilities=[
                AgentCapability.INTEGRATION,
                AgentCapability.API_INTEGRATION,
                AgentCapability.REASONING,
            ],
            default_parameters={
                "discovery_mode": "auto",
                "test_connection": True,
                "cache_results": True,
            },
            parameter_schema={
                "server_url": {"type": "string", "required": True},
                "authentication": {"type": "object", "required": False},
                "tools_filter": {"type": "array", "items": {"type": "string"}},
            },
            tags=["mcp", "integration", "tools"],
        )
