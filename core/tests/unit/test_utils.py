"""
Simple Unit Tests
================

Basic unit tests for AgentArea utility functions.
"""

from typing import Any

import pytest


def create_agent_config(name: str, model_type: str, planning: bool = False) -> dict[str, Any]:
    """Simple utility function to create agent configuration"""
    return {
        "name": name,
        "model_type": model_type,
        "planning_enabled": planning,
        "workflow_type": "sequential" if planning else "single",
        "tools_config": {"mcp_servers": [], "builtin_tools": [], "custom_tools": []},
    }


def validate_model_name(model_name: str) -> bool:
    """Validate model name format"""
    if not model_name:
        return False

    # Check for ollama format: ollama_chat/model_name
    if model_name.startswith("ollama_chat"):
        if "/" not in model_name:
            return False  # ollama_chat without slash is invalid
        parts = model_name.split("/")
        return len(parts) == 2 and len(parts[1]) > 0

    return True


def format_task_id(agent_id: str, user_id: str, timestamp: int) -> str:
    """Format task ID from components"""
    return f"task_{agent_id}_{user_id}_{timestamp}"


def parse_llm_response(response_text: str) -> dict[str, Any]:
    """Parse LLM response and extract content"""
    if not response_text:
        return {"content": "", "tokens": 0, "char_count": 0}

    stripped_content = response_text.strip()
    return {
        "content": stripped_content,
        "tokens": len(response_text.split()),
        "char_count": len(stripped_content),
    }


class TestUtils:
    """Unit tests for utility functions"""

    def test_create_agent_config_basic(self):
        """Test creating basic agent config"""
        config = create_agent_config("Test Agent", "ollama")

        assert config["name"] == "Test Agent"
        assert config["model_type"] == "ollama"
        assert config["planning_enabled"] is False
        assert config["workflow_type"] == "single"
        assert "tools_config" in config

    def test_create_agent_config_with_planning(self):
        """Test creating agent config with planning enabled"""
        config = create_agent_config("Planning Agent", "openai", planning=True)

        assert config["name"] == "Planning Agent"
        assert config["model_type"] == "openai"
        assert config["planning_enabled"] is True
        assert config["workflow_type"] == "sequential"

    def test_validate_model_name_ollama_valid(self):
        """Test validating valid ollama model names"""
        assert validate_model_name("ollama_chat/qwen2.5") is True
        assert validate_model_name("ollama_chat/llama2") is True
        assert validate_model_name("ollama_chat/mistral") is True

    def test_validate_model_name_ollama_invalid(self):
        """Test validating invalid ollama model names"""
        assert validate_model_name("ollama_chat/") is False
        assert validate_model_name("ollama_chat") is False
        assert validate_model_name("") is False

    def test_validate_model_name_other_valid(self):
        """Test validating other valid model names"""
        assert validate_model_name("gpt-4") is True
        assert validate_model_name("claude-3") is True
        assert validate_model_name("custom-model") is True

    def test_format_task_id(self):
        """Test formatting task IDs"""
        task_id = format_task_id("agent-123", "user-456", 1640995200)
        assert task_id == "task_agent-123_user-456_1640995200"

    def test_parse_llm_response_empty(self):
        """Test parsing empty LLM response"""
        result = parse_llm_response("")
        assert result["content"] == ""
        assert result["tokens"] == 0
        assert result["char_count"] == 0

    def test_parse_llm_response_simple(self):
        """Test parsing simple LLM response"""
        response = "Hello world!"
        result = parse_llm_response(response)

        assert result["content"] == "Hello world!"
        assert result["tokens"] == 2
        assert result["char_count"] == 12

    def test_parse_llm_response_with_whitespace(self):
        """Test parsing LLM response with whitespace"""
        response = "  This is a test response.  "
        result = parse_llm_response(response)

        assert result["content"] == "This is a test response."
        assert result["tokens"] == 5
        assert result["char_count"] == 24


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
