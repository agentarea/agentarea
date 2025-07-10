"""Agent Factory Service for creating agent instances."""

import logging
from typing import Any
from uuid import UUID

from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

logger = logging.getLogger(__name__)

# Optional import for TemporalLlmAgent
try:
    from agentarea_execution.temporal_llm_agent import create_temporal_llm_agent
    from agentarea_execution.interfaces import ActivityServicesInterface
    TEMPORAL_AVAILABLE = True
    logger.debug("TemporalFlow integration available")
except ImportError:
    TEMPORAL_AVAILABLE = False
    logger.debug("TemporalFlow integration not available")


class AgentFactoryService:
    """Service responsible for creating agent instances with proper configuration."""

    def __init__(
        self,
        activity_services: ActivityServicesInterface | None = None,
        enable_temporal_execution: bool = False,
    ):
        self.activity_services = activity_services
        self.enable_temporal_execution = enable_temporal_execution

        # Validate Temporal configuration
        if self.enable_temporal_execution:
            if not TEMPORAL_AVAILABLE:
                logger.warning("Temporal execution requested but TemporalFlow not available - falling back to standard execution")
                self.enable_temporal_execution = False
            elif not activity_services:
                logger.warning("Temporal execution requested but activity_services not provided - falling back to standard execution")
                self.enable_temporal_execution = False
            else:
                logger.info("TemporalFlow execution enabled")

    def create_litellm_model_from_instance(self, model_instance: Any) -> tuple[str, str | None]:
        """Create LiteLLM model string and endpoint URL from database model instance."""
        logger.info(f"Using model instance: {model_instance.name}")

        # Extract endpoint_url from provider_config
        endpoint_url = getattr(
            getattr(model_instance, "provider_config", None), "endpoint_url", None
        )

        # Construct LiteLLM model string from provider_spec and model_spec
        provider_config = getattr(model_instance, "provider_config", None)
        provider_spec = getattr(provider_config, "provider_spec", None)
        model_spec = getattr(model_instance, "model_spec", None)

        if not (provider_spec and model_spec):
            raise ValueError(
                "Model instance relationships not loaded - ensure provider_config, provider_spec, and model_spec are loaded"
            )

        litellm_model_string = f"{provider_spec.provider_type}/{model_spec.model_name}"
        logger.info(f"Created LiteLLM model string: {litellm_model_string}")

        return litellm_model_string, endpoint_url

    def create_llm_agent(
        self,
        agent_id: UUID,
        agent_config: dict[str, Any],
        tools: list[Any],
        litellm_model: LiteLlm,
    ) -> LlmAgent:
        """
        Create LLM agent - either standard LlmAgent or TemporalLlmAgent based on configuration.
        
        This method provides backward compatibility while enabling Temporal execution when available.
        """
        if self.enable_temporal_execution and TEMPORAL_AVAILABLE and self.activity_services:
            logger.info(f"Creating TemporalLlmAgent for agent {agent_id}")
            return create_temporal_llm_agent(
                activity_services=self.activity_services,
                agent_id=agent_id,
                name=agent_config["name"],
                model=litellm_model,
                instruction=agent_config["instruction"],
                tools=tools,
            )
        else:
            logger.info(f"Creating standard LlmAgent for agent {agent_id}")
            return LlmAgent(
                name=agent_config["name"],
                model=litellm_model,
                instruction=agent_config["instruction"],
                tools=tools,
            ) 