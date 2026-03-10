"""Agent execution activities for Temporal workflows.

This module provides Temporal activities for agent execution:

1. **State Management**: Uses TypedDict state passed between workflow activities
2. **Flow Control**: Workflow orchestrates activities step-by-step with conditional logic
3. **Tool Integration**: Direct MCP tool calls via execute_mcp_tool_activity
4. **Message Format**: OpenAI-compatible message format for LLM interactions
5. **Execution Model**: Activity-based with explicit Temporal workflow orchestration
6. **LLM Integration**: Uses real LLM services for model resolution and execution
"""

# Standard library imports
import logging
import os
from typing import Any
from uuid import UUID

from agentarea_agents_sdk import (
    GoalProgressEvaluator,
    LLMModel,
    LLMRequest,
    ToolExecutor,
    ToolManager,
)

# Local imports
from agentarea_common.auth.context import UserContext

# Third-party imports
from temporalio import activity

from ..interfaces import ActivityDependencies

# Add import for new Pydantic models
from ..models import (
    AgentConfigRequest,
    AgentConfigResult,
    ExecutionPlanRequest,
    ExecutionPlanResult,
    GoalEvaluationRequest,
    GoalEvaluationResult,
    LLMCallRequest,
    LLMCallResult,
    MCPToolRequest,
    MCPToolResult,
    SkillFileRequest,
    SkillFileResult,
    SkillInfo,
    ToolDiscoveryRequest,
    WorkflowEventsRequest,
    WorkflowEventsResult,
)
from .event_publisher import create_event_publisher, publish_enriched_llm_error_event

logger = logging.getLogger(__name__)


def make_agent_activities(dependencies: ActivityDependencies):
    """Factory function to create agent activities with injected dependencies.

    Args:
        dependencies: Basic dependencies needed to create services

    Returns:
        List of activity functions ready for worker registration
    """
    from .dependencies import (
        ActivityContext,
        ActivityServiceContainer,
        create_system_context,
        create_user_context,
    )

    # Create service container
    container = ActivityServiceContainer(dependencies)

    @activity.defn
    async def build_agent_config_activity(
        request: AgentConfigRequest,
    ) -> AgentConfigResult:
        """Build agent configuration including skills."""
        user_context = create_user_context(request.user_context_data)

        async with ActivityContext(container, user_context) as ctx:
            agent_service = await ctx.get_agent_service()

            # Get agent from database with skills
            agent = await agent_service.get_with_skills(request.agent_id)
            if not agent:
                raise ValueError(f"Agent {request.agent_id} not found")

            # Build skill information
            skills_info = []
            if hasattr(agent, "skills") and agent.skills:
                for skill in agent.skills:
                    # Get file list for multi-file skills
                    files = []
                    if skill.s3_path:
                        # For multi-file skills, we would list files from S3
                        # For now, just note it has additional files
                        files = ["(additional files available)"]

                    skills_info.append(
                        SkillInfo(
                            id=str(skill.id),
                            name=skill.name,
                            content=skill.content or "",
                            files=files,
                        )
                    )

            # Build configuration using Pydantic model
            return AgentConfigResult(
                id=str(agent.id),
                name=agent.name,
                description=agent.description,
                instruction=agent.instruction,
                model_id=request.override_model or agent.model_id,
                tools=agent.tools or [],
                events_config=agent.events_config or {},
                planning=agent.planning if agent.planning is not None else False,
                execution_context=request.execution_context,
                step_type=request.step_type,
                skills=skills_info,
            )

    @activity.defn
    async def discover_available_tools_activity(
        request: ToolDiscoveryRequest,
    ) -> list[dict[str, Any]]:  # Keep backward compatible
        """Discover available tools for an agent."""
        user_context = create_user_context(request.user_context_data)

        async with ActivityContext(container, user_context) as ctx:
            agent_service = await ctx.get_agent_service()
            mcp_server_instance_service = await ctx.get_mcp_server_instance_service()

            # Get agent configuration
            agent = await agent_service.get(request.agent_id)
            if not agent:
                raise ValueError(f"Agent {request.agent_id} not found")

            # Use tool manager to discover available tools
            tool_manager = ToolManager()
            base_url = os.environ.get("API_BASE_URL", "http://localhost:8000/api/v1")
            all_tools = await tool_manager.discover_available_tools(
                agent_id=request.agent_id,
                tools_config=agent.tools,
                mcp_server_instance_service=mcp_server_instance_service,
                agent_service=agent_service,
                base_url=base_url,
            )

            return all_tools

    @activity.defn
    async def call_llm_activity(
        request: LLMCallRequest,
    ) -> LLMCallResult:
        """Call LLM with messages and optional tools using streaming."""
        try:
            # model_id must be a UUID representing a model instance ID
            try:
                model_uuid = UUID(request.model_id)
            except ValueError as e:
                raise ValueError(
                    f"Invalid model_id: {request.model_id}. "
                    "Must be a valid UUID representing a model instance."
                ) from e

            # Create context - prefer workspace_id, fallback to user_context_data
            if request.workspace_id:
                user_context = create_system_context(request.workspace_id)
            elif request.user_context_data:
                user_context = create_user_context(request.user_context_data)
            else:
                raise ValueError("Either workspace_id or user_context_data must be provided")

            # Get model instance from database using clean DI
            async with ActivityContext(container, user_context) as ctx:
                model_instance_service = await ctx.get_model_instance_service()
                model_instance = await model_instance_service.get(model_uuid)
                if not model_instance:
                    raise ValueError(f"Model instance with ID {request.model_id} not found")

                # Extract required parameters from model instance
                provider_type = model_instance.provider_config.provider_spec.provider_type
                model_name = model_instance.model_spec.model_name
                endpoint_url = getattr(model_instance.model_spec, "endpoint_url", None)

                # Decode API key from secret manager
                # (provider_config.api_key is a secret name/placeholder)
                api_key = None
                api_key_secret_name = getattr(model_instance.provider_config, "api_key", None)
                if api_key_secret_name:
                    # Create secret manager from factory with workspace context
                    # We need to create a new session for the secret manager
                    from agentarea_common.config import get_database

                    secret_session = get_database().async_session_factory()
                    try:
                        secret_manager = dependencies.secret_manager_factory.create(
                            session=secret_session, user_context=user_context
                        )
                        api_key = await secret_manager.get_secret(api_key_secret_name)
                    finally:
                        await secret_session.close()
                else:
                    logger.warning(f"No API key found for model instance {model_instance.id}")

            # TODO: replace with proper config class
            docker_host = os.environ.get("LLM_DOCKER_HOST")
            if docker_host and provider_type == "ollama_chat":
                endpoint_url = f"http://{docker_host}:11434"

            llm_model = LLMModel(
                provider_type=provider_type,
                model_name=model_name,
                api_key=api_key,
                endpoint_url=endpoint_url,
            )

            # Create structured request
            llm_request = LLMRequest(
                messages=request.messages,
                tools=request.tools,
                temperature=request.temperature,
                max_tokens=request.max_tokens,
            )

            # Use streaming with ainvoke_stream and publish events
            complete_content = ""
            complete_tool_calls = None
            final_usage = None
            final_cost = 0.0
            chunk_index = 0

            # Create event publisher if we have task context
            event_publisher = None
            if request.task_id:
                event_publisher = create_event_publisher(dependencies.event_broker, request.task_id)

            # Stream the response and collect chunks
            async for chunk_response in llm_model.ainvoke_stream(llm_request):
                # Accumulate content
                if chunk_response.content:
                    complete_content += chunk_response.content

                    # Publish chunk event
                    if event_publisher:
                        await event_publisher(chunk_response.content, chunk_index, False)
                        chunk_index += 1

                # Update tool calls (they come complete in each chunk)
                if chunk_response.tool_calls:
                    complete_tool_calls = chunk_response.tool_calls

                # Update usage and cost information
                if chunk_response.usage:
                    final_usage = chunk_response.usage
                if chunk_response.cost:
                    final_cost = chunk_response.cost

            # Publish final chunk event
            if event_publisher:
                await event_publisher("", chunk_index, True)

            # Create final response using Pydantic model
            from ..models import LLMUsage

            usage_model = None
            if final_usage:
                usage_model = LLMUsage(
                    prompt_tokens=getattr(final_usage, "prompt_tokens", 0),
                    completion_tokens=getattr(final_usage, "completion_tokens", 0),
                    total_tokens=getattr(final_usage, "total_tokens", 0),
                )

            return LLMCallResult(
                role="assistant",
                content=complete_content,
                tool_calls=complete_tool_calls,
                cost=final_cost,
                usage=usage_model,
            )

        except Exception as e:
            # Enhanced error handling - create enriched error event if we have event context
            if request.task_id and request.agent_id and dependencies.event_broker:
                await publish_enriched_llm_error_event(
                    error=e,
                    task_id=request.task_id,
                    agent_id=request.agent_id,
                    execution_id=request.execution_id or "",
                    model_id=request.model_id,
                    provider_type=provider_type if "provider_type" in locals() else None,
                    event_broker=dependencies.event_broker,
                )

            # Legacy error handling for backward compatibility
            error_type = type(e).__name__
            error_message = str(e)

            # Simplified error raising - workflow will handle enriched events
            logger.error(f"LLM call failed: {error_message}")
            from temporalio.exceptions import ApplicationError

            # Import error checking functions from event_publisher
            from .event_publisher import _is_non_retryable_error

            raise ApplicationError(
                f"LLM call failed: {error_message}",
                type=error_type,
                non_retryable=_is_non_retryable_error(e),
            ) from e

    @activity.defn
    async def execute_mcp_tool_activity(
        request: MCPToolRequest,
    ) -> MCPToolResult:
        """Execute an MCP tool or built-in tool."""
        user_context = create_system_context(request.workspace_id)
        async with ActivityContext(container, user_context) as ctx:
            mcp_server_instance_service = await ctx.get_mcp_server_instance_service()

            # Create tool executor with properly configured code tools
            from agentarea_agents_sdk.tools.code_tools_loader import create_code_tool_instance
            from agentarea_agents_sdk.tools.decorator_tool import Toolset, ToolsetAdapter

            tool_executor = ToolExecutor()

            # Register code tools from configuration (new schema)
            if request.tools_config and isinstance(request.tools_config, list):
                for tool_config in request.tools_config:
                    if not isinstance(tool_config, dict):
                        continue

                    # Only process code tools here
                    if tool_config.get("type") != "code":
                        continue

                    tool_name = tool_config.get("name")
                    if not tool_name:
                        continue

                    # Extract settings
                    settings = tool_config.get("settings", {})
                    disabled_methods = settings.get("disabled_methods", [])

                    # Convert disabled_methods to constructor arguments
                    toolset_methods = (
                        dict.fromkeys(disabled_methods, False) if disabled_methods else {}
                    )

                    # Create and register the code tool instance
                    tool_instance = create_code_tool_instance(tool_name, toolset_methods)
                    if tool_instance:
                        # Check if tool is a Toolset - if so, wrap it in adapter for compatibility
                        if isinstance(tool_instance, Toolset):
                            tool_instance = ToolsetAdapter(tool_instance)

                        tool_executor.register_tool(tool_instance)
                        logger.info(f"Registered code tool for execution: {tool_name}")
                    else:
                        logger.warning(f"Unknown code tool requested: {tool_name}")

            # Register agent tools from configuration
            if request.tools and isinstance(request.tools, list):
                agent_configs = [
                    tc
                    for tc in request.tools
                    if isinstance(tc, dict) and tc.get("type") == "agent"
                ]
                if agent_configs:
                    base_url = os.environ.get(
                        "API_BASE_URL", "http://localhost:8000/api/v1"
                    )
                    agent_service = await ctx.get_agent_service()

                    for tool_config in agent_configs:
                        agent_name = tool_config.get("name")
                        if not agent_name:
                            continue

                        from agentarea_agents_sdk.tools.a2a_tool_factory import (
                            A2AAgentToolFactory,
                        )

                        a2a_tool = await A2AAgentToolFactory.create_tool(
                            agent_name=agent_name,
                            agent_service=agent_service,
                            base_url=base_url,
                            a2a_url_override=(tool_config.get("settings") or {}).get(
                                "a2a_url"
                            ),
                        )
                        if a2a_tool:
                            tool_executor.register_tool(a2a_tool)
                            logger.info(
                                f"Registered agent tool for execution: {agent_name}"
                            )

            try:
                result = await tool_executor.execute_tool(
                    tool_name=request.tool_name,
                    tool_args=request.tool_args,
                    server_instance_id=request.server_instance_id,
                    mcp_server_instance_service=mcp_server_instance_service,
                )

                return MCPToolResult(
                    success=result.get("success", False),
                    result=str(result.get("result", "")),
                    execution_time=result.get("execution_time", ""),
                )

            except Exception as e:
                logger.error(f"Tool execution failed: {e}")
                return MCPToolResult(
                    success=False,
                    result="",
                    execution_time="",
                    error=str(e),
                )

    @activity.defn
    async def create_execution_plan_activity(
        request: ExecutionPlanRequest,
    ) -> ExecutionPlanResult:
        """Create an execution plan based on the goal and available tools."""
        try:
            # For now, return a simple plan - could be enhanced with actual LLM call
            tool_names = [tool.get("name", "unknown") for tool in request.available_tools]

            return ExecutionPlanResult(
                plan=(
                    f"Execute the task '{request.goal.get('description', 'Unknown')}' "
                    "systematically using available tools"
                ),
                estimated_steps=min(max(len(request.available_tools), 3), 8),  # Between 3-8 steps
                key_tools=tool_names[:3],  # First 3 tools
                risk_factors=[
                    "Tool execution failures",
                    "LLM response issues",
                    "External API timeouts",
                ],
            )

        except Exception as e:
            logger.error(f"Failed to create execution plan: {e}")
            return ExecutionPlanResult(
                plan=(
                    f"Execute the task '{request.goal.get('description', 'Unknown')}' step by step"
                ),
                estimated_steps=5,
                key_tools=[],
                risk_factors=["Planning failed - proceeding with default approach"],
            )

    @activity.defn
    async def evaluate_goal_progress_activity(
        request: GoalEvaluationRequest,
    ) -> GoalEvaluationResult:
        """Evaluate progress toward the goal."""
        evaluator = GoalProgressEvaluator()

        # Extract goal information for the new interface
        goal_description = request.goal.get("description", "")
        success_criteria = request.goal.get("success_criteria", [])

        evaluation = await evaluator.evaluate_progress(
            goal_description=goal_description,
            success_criteria=success_criteria,
            conversation_history=request.messages,
            current_iteration=request.current_iteration,
        )

        return GoalEvaluationResult(
            goal_achieved=evaluation.get("goal_achieved", False),
            confidence=evaluation.get("confidence", 0.0),
            final_response=evaluation.get("final_response"),
            reasoning=evaluation.get("reasoning", ""),
            next_steps=evaluation.get("next_steps", []),
        )

    @activity.defn
    async def publish_workflow_events_activity(
        request: WorkflowEventsRequest,
    ) -> WorkflowEventsResult:
        """Publish workflow events."""
        try:
            import json
            from datetime import datetime
            from uuid import uuid4

            from agentarea_common.events.base_events import DomainEvent
            from agentarea_common.events.router import create_event_broker_from_router

            from ..handlers import handle_llm_error_event

            logger.info(f"Publishing {len(request.events_json)} workflow events via EventBroker")

            # Convert RedisRouter to RedisEventBroker for publishing
            # dependencies.event_broker is a RedisRouter, we need RedisEventBroker to publish
            if not hasattr(dependencies.event_broker, "broker"):
                logger.error(
                    f"Event broker {type(dependencies.event_broker)} "
                    "does not have 'broker' attribute"
                )
                return WorkflowEventsResult(
                    success=False, errors=["Event broker configuration error"]
                )

            redis_event_broker = create_event_broker_from_router(dependencies.event_broker)  # type: ignore
            events_published = 0
            errors = []

            for event_json in request.events_json:
                try:
                    event = json.loads(event_json)
                    task_id = event.get("data", {}).get("task_id", "unknown")

                    # Create proper domain event with correct parameters
                    domain_event = DomainEvent(
                        event_id=event.get("event_id", str(uuid4())),
                        event_type=f"workflow.{event['event_type']}",  # Prefix for workflow events
                        timestamp=datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00")),
                        # All other data goes into the data dict
                        aggregate_id=task_id,
                        aggregate_type="task",
                        original_event_type=event["event_type"],
                        original_timestamp=event["timestamp"],
                        original_data=event[
                            "data"
                        ],  # Include the original event data for tool calls
                    )

                    # 1. Publish via RedisEventBroker (uses FastStream
                    # infrastructure) for real-time SSE
                    await redis_event_broker.publish(domain_event)
                    logger.debug(
                        f"Published workflow event: {event['event_type']} for task {task_id}"
                    )

                    # 2. Store event in database using proper service layer
                    try:
                        # Use workspace_id and user_id from workflow request (already present)
                        workspace_id = request.workspace_id
                        user_id = request.user_id

                        # Create proper user context with values from workflow
                        user_context = UserContext(
                            user_id=user_id,
                            workspace_id=workspace_id,
                        )

                        async with ActivityContext(container, user_context) as ctx:
                            task_event_service = await ctx.get_task_event_service()

                            # Create event using service - workspace_id and created_by are provided
                            await task_event_service.create_workflow_event(
                                task_id=UUID(task_id),
                                event_type=event["event_type"],
                                data=event["data"],
                                workspace_id=workspace_id,
                                created_by=user_id,
                            )

                            # Commit is handled by the service
                            logger.debug(
                                f"Stored event using service: {event['event_type']} for task {task_id}"
                            )

                    except Exception as db_error:
                        logger.error(f"Failed to store event using service: {db_error}")
                        errors.append(f"DB storage failed for {event['event_type']}: {db_error!s}")

                    # 3. Handle LLM error events locally for immediate action
                    if event["event_type"].startswith("LLM") and "Failed" in event["event_type"]:
                        try:
                            await handle_llm_error_event(domain_event)
                        except Exception as handler_error:
                            logger.error(f"Failed to handle LLM error event: {handler_error}")
                            errors.append(f"Error handler failed: {handler_error!s}")

                    events_published += 1

                except Exception as event_error:
                    logger.error(f"Failed to process single event: {event_error}")
                    errors.append(f"Event processing failed: {event_error!s}")

            return WorkflowEventsResult(
                success=len(errors) == 0,
                events_published=events_published,
                errors=errors,
            )

        except Exception as e:
            logger.error(f"Failed to publish workflow events: {e}")
            return WorkflowEventsResult(
                success=False,
                events_published=0,
                errors=[f"Critical failure: {e!s}"],
            )

    @activity.defn
    async def resolve_skill_file_activity(
        request: SkillFileRequest,
    ) -> SkillFileResult:
        """Resolve a file from a skill package.

        This activity retrieves a file from a skill's S3 storage,
        returning either the content directly or a presigned URL
        for larger files.
        """
        try:
            from agentarea_agents.infrastructure.skill_storage_service import (
                SkillStorageService,
            )

            user_context = create_system_context(request.workspace_id)

            async with ActivityContext(container, user_context) as ctx:
                # Get skill from database
                skill_service = await ctx.get_skill_service()
                skill = await skill_service.get(request.skill_id)

                if not skill:
                    return SkillFileResult(
                        success=False,
                        error=f"Skill {request.skill_id} not found",
                    )

                # Handle content-only skills
                if not skill.s3_path:
                    # For content-only skills, check if requesting the main file
                    if request.file_path.lower() in ("skill.md", "readme.md"):
                        content = skill.content or ""
                        return SkillFileResult(
                            success=True,
                            content=content.encode("utf-8"),
                            content_text=content,
                            content_type="text/markdown",
                            size=len(content),
                        )
                    return SkillFileResult(
                        success=False,
                        error=f"Skill {request.skill_id} has no file storage (content-only)",
                    )

                # Get file from S3
                storage_service = SkillStorageService()

                try:
                    content = await storage_service.get_file_content(
                        skill.s3_path,
                        request.file_path,
                    )

                    # Determine content type
                    content_type = storage_service._guess_content_type(request.file_path)

                    # For text files, also provide text representation
                    content_text = None
                    if content_type.startswith("text/") or content_type in (
                        "application/json",
                        "application/x-yaml",
                    ):
                        try:
                            content_text = content.decode("utf-8")
                        except UnicodeDecodeError:
                            pass  # Binary content

                    return SkillFileResult(
                        success=True,
                        content=content,
                        content_text=content_text,
                        content_type=content_type,
                        size=len(content),
                    )

                except FileNotFoundError:
                    return SkillFileResult(
                        success=False,
                        error=f"File not found: {request.file_path}",
                    )

        except Exception as e:
            logger.error(f"Failed to resolve skill file: {e}")
            return SkillFileResult(
                success=False,
                error=str(e),
            )

    # Return all activity functions
    return [
        build_agent_config_activity,
        discover_available_tools_activity,
        call_llm_activity,
        execute_mcp_tool_activity,
        create_execution_plan_activity,
        evaluate_goal_progress_activity,
        publish_workflow_events_activity,
        resolve_skill_file_activity,
    ]
