"""Temporal interceptors for ADK calls.

This module provides interceptors that ensure ALL tool and LLM calls
from ADK are routed through Temporal activities, providing:

- Retry capabilities for every call
- Observability and tracing
- Workflow orchestration
- Error handling and recovery
"""

import logging
from typing import Dict, Any

from .tool_call_interceptor import enable_tool_call_interception, disable_tool_call_interception
from .llm_call_interceptor import enable_llm_call_interception, disable_llm_call_interception

logger = logging.getLogger(__name__)


class TemporalInterceptorManager:
    """Manager for enabling/disabling Temporal interceptors."""
    
    _interceptors_enabled = False
    
    @classmethod
    def enable_all_interceptors(cls):
        """Enable all Temporal interceptors for ADK calls."""
        if cls._interceptors_enabled:
            logger.info("Temporal interceptors already enabled")
            return
        
        logger.info("🚀 Enabling Temporal interceptors for ALL ADK calls...")
        
        # Enable tool call interception
        enable_tool_call_interception()
        
        # Enable LLM call interception
        enable_llm_call_interception()
        
        cls._interceptors_enabled = True
        logger.info("✅ All Temporal interceptors enabled - every tool and LLM call will be a Temporal activity")
    
    @classmethod
    def disable_all_interceptors(cls):
        """Disable all Temporal interceptors."""
        if not cls._interceptors_enabled:
            logger.info("Temporal interceptors already disabled")
            return
        
        logger.info("🛑 Disabling Temporal interceptors...")
        
        # Disable tool call interception
        disable_tool_call_interception()
        
        # Disable LLM call interception
        disable_llm_call_interception()
        
        cls._interceptors_enabled = False
        logger.info("✅ All Temporal interceptors disabled")
    
    @classmethod
    def is_enabled(cls) -> bool:
        """Check if interceptors are enabled."""
        return cls._interceptors_enabled


def enable_temporal_backbone():
    """Enable Temporal backbone for all ADK calls.
    
    This function ensures that EVERY tool call and LLM call from ADK
    becomes a Temporal activity, providing full workflow orchestration.
    """
    TemporalInterceptorManager.enable_all_interceptors()


def disable_temporal_backbone():
    """Disable Temporal backbone for ADK calls."""
    TemporalInterceptorManager.disable_all_interceptors()


def is_temporal_backbone_enabled() -> bool:
    """Check if Temporal backbone is enabled."""
    return TemporalInterceptorManager.is_enabled()