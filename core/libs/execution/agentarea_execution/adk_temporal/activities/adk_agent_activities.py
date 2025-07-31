"""ADK Agent Activities for Temporal workflows."""

import logging
from typing import Any, AsyncGenerator, Dict, List, Optional

from temporalio import activity
from google.genai import types

from ...ag.adk.agents.run_config import RunConfig
from ...ag.adk.events.event import Event

from ..services.adk_service_factory import create_adk_runner
from ..utils.event_serializer import EventSerializer
from ..utils.agent_builder import build_adk_agent_from_config, validate_agent_config

logger = logging.getLogger(__name__)


@activity.defn
async def validate_agent_configuration(
    agent_config: Dict[str, Any]
) -> bool:
    """Validate ADK agent configuration.
    
    Args:
        agent_config: Dictionary containing agent configuration
        
    Returns:
        True if configuration is valid, False otherwise
        
    Raises:
        ValueError: If configuration is invalid
    """
    try:
        activity_info = activity.info()
        logger.info(f"Validating agent configuration - Activity: {activity_info.activity_type}")
    except RuntimeError:
        logger.info("Validating agent configuration - Direct mode")
    
    if not validate_agent_config(agent_config):
        raise ValueError("Invalid agent configuration")
    
    return True


@activity.defn
async def create_agent_runner(
    agent_config: Dict[str, Any],
    session_data: Dict[str, Any]
) -> None:
    """Create ADK runner with service bridges.
    
    Args:
        agent_config: Dictionary containing agent configuration
        session_data: Dictionary containing session information
        
    Returns:
        None
        
    Raises:
        Exception: If runner creation fails
    """
    try:
        activity_info = activity.info()
        logger.info(f"Creating agent runner - Activity: {activity_info.activity_type}")
    except RuntimeError:
        logger.info("Creating agent runner - Direct mode")
    
    try:
        # Create ADK runner with service bridges
        runner = create_adk_runner(agent_config, session_data)
        logger.info("Successfully created ADK runner")
    except Exception as e:
        logger.error(f"Failed to create ADK runner: {str(e)}", exc_info=True)
        raise


@activity.defn
async def execute_agent_step(
    agent_config: Dict[str, Any],
    session_data: Dict[str, Any],
    user_message: Dict[str, Any],
    run_config: Optional[Dict[str, Any]] = None
) -> List[Dict[str, Any]]:
    """Execute a single step of ADK agent execution with Temporal backbone.
    
    Args:
        agent_config: Dictionary containing agent configuration
        session_data: Dictionary containing session information
        user_message: Dictionary containing user message content
        run_config: Optional run configuration
        
    Returns:
        List of serialized event dictionaries from this step
        
    Raises:
        Exception: If agent execution fails
    """
    try:
        activity_info = activity.info()
        logger.info(f"Executing agent step - Activity: {activity_info.activity_type}")
    except RuntimeError:
        logger.info("Executing agent step - Direct mode")
    
    try:
        # Create ADK runner with Temporal backbone enabled
        runner = create_adk_runner(
            agent_config, 
            session_data, 
            use_temporal_services=False,  # Keep session services simple
            use_temporal_backbone=True    # Enable Temporal for tool/LLM calls
        )
        
        # Convert user message to ADK Content
        user_content = _dict_to_adk_content(user_message)
        
        # Prepare run config - always provide a default
        adk_run_config = RunConfig(**run_config) if run_config else RunConfig()
        
        # Execute agent and collect events
        events = []
        event_count = 0
        
        logger.info(f"Starting Temporal-backed agent step for agent: {agent_config.get('name', 'unknown')}")
        
        # Heartbeat to prevent timeout during long-running operations
        activity.heartbeat("Executing ADK agent step with Temporal backbone...")
        
        async for event in runner.run_async(
            user_id=session_data.get("user_id", "default"),
            session_id=session_data.get("session_id", "default"),
            new_message=user_content,
            run_config=adk_run_config
        ):
            event_count += 1
            
            # Serialize event for Temporal storage
            event_dict = EventSerializer.event_to_dict(event)
            events.append(event_dict)
            
            # Log progress periodically
            if event_count % 5 == 0:
                logger.info(f"Processed {event_count} events")
                # Send heartbeat every 5 events
                activity.heartbeat(f"Processed {event_count} events")
            
            # Check if this is the final response
            if event.is_final_response():
                logger.info(f"Agent step completed with final response after {event_count} events")
                break
                
        # Final heartbeat before completion
        activity.heartbeat("Finalizing agent step...")
        
        logger.info(f"ADK agent step completed with Temporal backbone - Events: {len(events)}")
        return events
        
    except Exception as e:
        logger.error(f"ADK agent step execution failed: {str(e)}", exc_info=True)
        
        # Create error event
        error_event = Event(
            author=agent_config.get("name", "agent"),
            content=types.Content(parts=[
                types.Part(text=f"Agent step execution failed: {str(e)}")
            ])
        )
        
        return [EventSerializer.event_to_dict(error_event)]


@activity.defn  
async def stream_adk_agent_activity(
    agent_config: Dict[str, Any],
    session_data: Dict[str, Any],
    user_message: Dict[str, Any],
    run_config: Optional[Dict[str, Any]] = None
) -> AsyncGenerator[Dict[str, Any], None]:
    """Execute ADK agent with streaming event delivery.
    
    This activity streams events as they occur during agent execution,
    allowing for real-time updates in the workflow.
    
    Args:
        agent_config: Dictionary containing agent configuration
        session_data: Dictionary containing session information  
        user_message: Dictionary containing user message content
        run_config: Optional run configuration
        
    Yields:
        Serialized event dictionaries as they occur
        
    Raises:
        ValueError: If configuration is invalid
        Exception: If agent execution fails
    """
    activity_info = activity.info()
    logger.info(f"Starting streaming ADK agent execution - Activity: {activity_info.activity_type}")
    
    try:
        # Validate inputs (same as non-streaming version)
        if not validate_agent_config(agent_config):
            raise ValueError("Invalid agent configuration")
        
        if not user_message.get("content"):
            raise ValueError("User message content is required")
        
        # Create ADK runner
        runner = create_adk_runner(agent_config, session_data)
        
        # Convert user message to ADK Content
        user_content = _dict_to_adk_content(user_message)
        
        # Prepare run config - always provide a default
        adk_run_config = RunConfig(**run_config) if run_config else RunConfig()
        
        # Execute agent and stream events
        event_count = 0
        
        logger.info(f"Starting streaming execution for agent: {agent_config.get('name', 'unknown')}")
        
        # Heartbeat to prevent timeout during long-running operations
        activity.heartbeat("Executing ADK agent...")
        
        async for event in runner.run_async(
            user_id=session_data.get("user_id", "default"),
            session_id=session_data.get("session_id", "default"),
            new_message=user_content,
            run_config=adk_run_config
        ):
            event_count += 1
            
            # Serialize and yield event immediately
            event_dict = EventSerializer.event_to_dict(event)
            yield event_dict
            
            # Log progress
            if event_count % 5 == 0:
                logger.info(f"Streamed {event_count} events")
                # Send heartbeat every 5 events
                activity.heartbeat(f"Streamed {event_count} events")
            
            # Break on final response
            if event.is_final_response():
                logger.info(f"Streaming completed after {event_count} events")
                break
        
        # Final heartbeat before completion
        activity.heartbeat("Finalizing streaming execution...")
        
    except Exception as e:
        logger.error(f"Streaming ADK agent execution failed: {str(e)}", exc_info=True)
        
        # Yield error event
        error_event = Event(
            author=agent_config.get("name", "agent"),
            content=types.Content(parts=[
                types.Part(text=f"Streaming execution failed: {str(e)}")
            ])
        )
        
        yield EventSerializer.event_to_dict(error_event)


def _dict_to_adk_content(message_dict: Dict[str, Any]) -> types.Content:
    """Convert message dictionary to ADK Content object.
    
    Args:
        message_dict: Dictionary containing message content
        
    Returns:
        ADK Content object
    """
    content_data = message_dict.get("content", {})
    
    # Handle different content formats
    if isinstance(content_data, str):
        # Simple text content
        return types.Content(parts=[types.Part(text=content_data)])
    elif isinstance(content_data, dict):
        # Structured content - try to deserialize
        deserialized = EventSerializer.deserialize_content(content_data)
        return deserialized if deserialized is not None else types.Content(parts=[types.Part(text=str(content_data))])
    else:
        # Fallback to string representation
        return types.Content(parts=[types.Part(text=str(content_data))])


@activity.defn
async def validate_adk_agent_config(agent_config: Dict[str, Any]) -> Dict[str, Any]:
    """Validate ADK agent configuration.
    
    Args:
        agent_config: Dictionary containing agent configuration
        
    Returns:
        Dictionary with validation results:
        - valid: boolean indicating if config is valid
        - errors: list of validation error messages
        - warnings: list of warning messages
    """
    logger.info("Validating ADK agent configuration")
    
    errors = []
    warnings = []
    
    try:
        # Basic validation
        if not validate_agent_config(agent_config):
            errors.append("Agent configuration failed basic validation")
        
        # Check required fields
        if not agent_config.get("name"):
            errors.append("Agent name is required")
        elif not isinstance(agent_config["name"], str):
            errors.append("Agent name must be a string")
        
        # Check model
        model = agent_config.get("model")
        if not model:
            warnings.append("No model specified, will use default")
        elif not isinstance(model, str):
            errors.append("Model must be a string")
        
        # Check tools
        tools = agent_config.get("tools", [])
        if tools and not isinstance(tools, list):
            errors.append("Tools must be a list")
        else:
            for i, tool_config in enumerate(tools):
                if not isinstance(tool_config, dict):
                    errors.append(f"Tool {i} must be a dictionary")
                elif not tool_config.get("name"):
                    errors.append(f"Tool {i} missing required 'name' field")
        
        # Try to build agent to catch construction errors
        if not errors:
            try:
                agent = build_adk_agent_from_config(agent_config)
                if not agent:
                    errors.append("Failed to build agent from configuration")
            except Exception as e:
                errors.append(f"Agent construction failed: {str(e)}")
        
        result = {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings
        }
        
        logger.info(f"Configuration validation completed - Valid: {result['valid']}, Errors: {len(errors)}, Warnings: {len(warnings)}")
        return result
        
    except Exception as e:
        logger.error(f"Configuration validation failed: {str(e)}", exc_info=True)
        return {
            "valid": False,
            "errors": [f"Validation failed: {str(e)}"],
            "warnings": warnings
        }

@activity.defn
async def execute_llm_call(
    agent_config: Dict[str, Any],
    session_data: Dict[str, Any],
    llm_request: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute LLM call as a Temporal activity."""
    logger.info("Executing LLM call activity")
    from ..utils.agent_builder import build_adk_agent_from_config
    agent = build_adk_agent_from_config(agent_config)
    model = agent.canonical_model
    request = types.GenerateContentRequest(
        contents=llm_request['contents'],
        system_instruction=types.Content(parts=[types.Part(text=llm_request['system_instruction'])]),
        tools=[types.Tool(function_declarations=t) for t in llm_request['tools']],
        generation_config=types.GenerationConfig(**llm_request['generation_config'])
    )
    response = await model.generate_content_async(request)
    # Convert to dict or serialize appropriately
    return EventSerializer.serialize_llm_response(response)

@activity.defn
async def execute_tool_call(
    agent_config: Dict[str, Any],
    session_data: Dict[str, Any],
    tool_request: Dict[str, Any]
) -> Dict[str, Any]:
    """Execute tool call as a Temporal activity."""
    logger.info("Executing tool call activity")
    from ..utils.agent_builder import build_adk_agent_from_config
    agent = build_adk_agent_from_config(agent_config)
    tools = await agent.canonical_tools()
    tool_name = tool_request['name']
    tool_args = tool_request['args']
    tool = next((t for t in tools if t.name == tool_name), None)
    if not tool:
        raise ValueError(f"Tool {tool_name} not found")
    tool_context = ToolContext(session_state=session_data.get('state', {}))
    result = await tool.execute(tool_args, tool_context)
    return EventSerializer.serialize_tool_result(result)
