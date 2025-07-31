"""ADK service factory for creating Temporal-integrated ADK runners."""

import logging
from typing import Any, Dict, Optional

from ...ag.adk.runners import Runner
from ...ag.adk.artifacts.in_memory_artifact_service import InMemoryArtifactService
from ...ag.adk.memory.in_memory_memory_service import InMemoryMemoryService  
from ...ag.adk.auth.credential_service.in_memory_credential_service import InMemoryCredentialService

from .temporal_session_service import TemporalSessionService
from .temporal_artifact_service import TemporalArtifactService
from .temporal_memory_service import TemporalMemoryService
from .temporal_llm_service import TemporalLlmServiceFactory
from .temporal_tool_service import TemporalToolRegistry
from ..utils.agent_builder import build_adk_agent_from_config, build_temporal_enhanced_agent
from ..interceptors import enable_temporal_backbone, disable_temporal_backbone, is_temporal_backbone_enabled

logger = logging.getLogger(__name__)


def create_adk_runner(
    agent_config: Dict[str, Any],
    session_data: Dict[str, Any],
    use_temporal_services: bool = False,  # Default to in-memory services for simplicity
    use_temporal_backbone: bool = True   # NEW: Use Temporal for tool/LLM execution
) -> Runner:
    """Create an ADK Runner with appropriate service implementations.
    
    Args:
        agent_config: Dictionary containing agent configuration
        session_data: Dictionary containing session information
        use_temporal_services: Whether to use Temporal-aware service implementations
        use_temporal_backbone: Whether to route tool/LLM calls through Temporal
        
    Returns:
        Configured ADK Runner instance
    """
    logger.info(f"Creating ADK runner for agent: {agent_config.get('name', 'unknown')}")
    
    try:
        # Enable/disable Temporal backbone based on configuration
        if use_temporal_backbone and not is_temporal_backbone_enabled():
            logger.info("🔧 Enabling Temporal backbone - ALL tool and LLM calls will be Temporal activities")
            enable_temporal_backbone()
        elif not use_temporal_backbone and is_temporal_backbone_enabled():
            logger.info("🔧 Disabling Temporal backbone - using standard ADK execution")
            disable_temporal_backbone()
        
        # Build the ADK agent from configuration
        if use_temporal_backbone:
            # Use enhanced agent builder that integrates Temporal services
            agent = build_temporal_enhanced_agent(agent_config, session_data)
            logger.info("Created Temporal-enhanced ADK agent with interceptors enabled")
        else:
            # Use standard ADK agent
            agent = build_adk_agent_from_config(agent_config)
            logger.info("Created standard ADK agent")
        
        # Use ADK's built-in in-memory services for simplicity
        # These handle all the serialization and state management automatically
        artifact_service = InMemoryArtifactService()
        memory_service = InMemoryMemoryService()
        credential_service = InMemoryCredentialService()
        
        # For session service, use temporal version if requested, otherwise use in-memory
        if use_temporal_services:
            session_service = TemporalSessionService(session_data)
        else:
            # Use ADK's in-memory session service as default
            from ...ag.adk.sessions.in_memory_session_service import InMemorySessionService
            session_service = InMemorySessionService()
        
        # Create runner with services
        runner = Runner(
            app_name=session_data.get("app_name", "agentarea"),
            agent=agent,
            session_service=session_service,
            artifact_service=artifact_service,
            memory_service=memory_service,
            credential_service=credential_service,
        )
        
        service_type = "temporal-enhanced" if use_temporal_backbone else ("temporal session" if use_temporal_services else "default")
        logger.info(f"Successfully created ADK runner with {service_type} services")
        return runner
        
    except Exception as e:
        logger.error(f"Failed to create ADK runner: {e}")
        raise


def create_default_session_data(
    user_id: str = "default",
    session_id: Optional[str] = None,
    app_name: str = "agentarea",
    initial_state: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Create default session data dictionary.
    
    Args:
        user_id: User identifier
        session_id: Optional session identifier
        app_name: Application name
        initial_state: Optional initial session state
        
    Returns:
        Session data dictionary
    """
    if session_id is None:
        import time
        session_id = f"session_{user_id}_{int(time.time())}"
    
    return {
        "user_id": user_id,
        "session_id": session_id,
        "app_name": app_name,
        "state": initial_state or {},
        "created_time": time.time(),
    }


def validate_runner_config(
    agent_config: Dict[str, Any],
    session_data: Dict[str, Any]
) -> bool:
    """Validate configuration for creating ADK runner.
    
    Args:
        agent_config: Agent configuration dictionary
        session_data: Session data dictionary
        
    Returns:
        True if valid, False otherwise
    """
    try:
        # Check agent config
        if not isinstance(agent_config, dict):
            logger.error("Agent config must be a dictionary")
            return False
        
        if not agent_config.get("name"):
            logger.error("Agent config must have a 'name' field")
            return False
        
        # Check session data
        if not isinstance(session_data, dict):
            logger.error("Session data must be a dictionary")
            return False
        
        required_session_fields = ["user_id", "session_id", "app_name"]
        for field in required_session_fields:
            if not session_data.get(field):
                logger.error(f"Session data must have a '{field}' field")
                return False
        
        return True
        
    except Exception as e:
        logger.error(f"Validation failed: {e}")
        return False


def create_runner_from_workflow_state(workflow_state: Dict[str, Any]) -> Runner:
    """Create ADK runner from Temporal workflow state.
    
    This is useful for resuming agent execution from persisted workflow state.
    
    Args:
        workflow_state: Dictionary containing persisted workflow state
        
    Returns:
        Configured ADK Runner instance
    """
    logger.info("Creating ADK runner from workflow state")
    
    try:
        agent_config = workflow_state.get("agent_config", {})
        session_data = workflow_state.get("session_data", {})
        
        if not validate_runner_config(agent_config, session_data):
            raise ValueError("Invalid workflow state for runner creation")
        
        # Create runner with temporal services
        runner = create_adk_runner(agent_config, session_data, use_temporal_services=True)
        
        # Restore service state if available
        services_state = workflow_state.get("services_state", {})
        if services_state:
            restore_service_state(runner, services_state)
        
        logger.info("Successfully created runner from workflow state")
        return runner
        
    except Exception as e:
        logger.error(f"Failed to create runner from workflow state: {e}")
        raise


def extract_runner_state(runner: Runner) -> Dict[str, Any]:
    """Extract state from ADK runner for Temporal workflow persistence.
    
    Args:
        runner: ADK Runner instance
        
    Returns:
        Dictionary containing runner state
    """
    try:
        state = {
            "app_name": runner.app_name,
            "agent_metadata": {
                "name": runner.agent.name,
                "description": runner.agent.description,
                "type": type(runner.agent).__name__,
            }
        }
        
        # Extract service states if they have the capability
        if hasattr(runner.session_service, 'get_session_data'):
            state["session_service_state"] = runner.session_service.get_session_data()
        
        if hasattr(runner.artifact_service, 'get_artifact_data'):
            state["artifact_service_state"] = runner.artifact_service.get_artifact_data()
        
        if hasattr(runner.memory_service, 'get_memory_data'):
            state["memory_service_state"] = runner.memory_service.get_memory_data()
        
        return state
        
    except Exception as e:
        logger.error(f"Failed to extract runner state: {e}")
        return {}


def restore_service_state(runner: Runner, services_state: Dict[str, Any]) -> None:
    """Restore service state to an ADK runner.
    
    Args:
        runner: ADK Runner instance
        services_state: Dictionary containing service states
    """
    try:
        # Restore session service state
        if "session_service_state" in services_state and hasattr(runner.session_service, 'load_session_data'):
            runner.session_service.load_session_data(services_state["session_service_state"])
        
        # Restore artifact service state
        if "artifact_service_state" in services_state and hasattr(runner.artifact_service, 'load_artifact_data'):
            runner.artifact_service.load_artifact_data(services_state["artifact_service_state"])
        
        # Restore memory service state
        if "memory_service_state" in services_state and hasattr(runner.memory_service, 'load_memory_data'):
            runner.memory_service.load_memory_data(services_state["memory_service_state"])
        
        logger.info("Successfully restored service state")
        
    except Exception as e:
        logger.error(f"Failed to restore service state: {e}")