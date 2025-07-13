"""
LLMModelResolver: Utility for resolving LiteLLM model strings from agent config.

This abstraction allows the execution layer to decouple LLM orchestration from model string formatting.
For now, it always returns 'ollama_chat/qwen2.5' (for E2E/local dev), but can be extended for DB-driven config.
"""

from typing import Dict, Any

class LLMModelResolver:
    """
    Resolves the LiteLLM model string to use for a given agent config.
    """
    def get_litellm_model(self, agent_config: Dict[str, Any]) -> str:
        # TODO: Extend to use agent_config/model_instance from DB
        # For E2E: always use local Ollama Qwen2.5
        return "ollama_chat/qwen2.5" 