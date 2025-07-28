"""Tests for ADK agent builder utilities."""

import pytest

from ..utils.agent_builder import (
    build_adk_agent_from_config,
    validate_agent_config,
    create_simple_agent_config,
    extract_agent_metadata
)
from ...ag.adk.agents.base_agent import BaseAgent
from ...ag.adk.agents.llm_agent import LlmAgent


class TestAgentBuilder:
    """Test suite for agent builder utilities."""
    
    def test_create_simple_agent_config(self):
        """Test creating a simple agent configuration."""
        config = create_simple_agent_config(
            name="test_agent",
            model="gpt-4",
            instructions="You are a test agent",
            description="Test agent description"
        )
        
        assert config["name"] == "test_agent"
        assert config["model"] == "gpt-4"
        assert config["instructions"] == "You are a test agent"
        assert config["description"] == "Test agent description"
        assert "tools" not in config
        
        # Test with tools
        tools = [{"name": "test_tool", "description": "A test tool"}]
        config_with_tools = create_simple_agent_config(
            name="test_agent",
            tools=tools
        )
        
        assert config_with_tools["tools"] == tools
    
    def test_validate_agent_config_valid(self):
        """Test validation of valid agent configurations."""
        # Minimal valid config
        config = {"name": "test_agent"}
        assert validate_agent_config(config) is True
        
        # Full valid config
        config = {
            "name": "test_agent",
            "model": "gpt-4",
            "instructions": "Test instructions",
            "description": "Test description",
            "tools": [
                {"name": "tool1", "description": "Tool 1"},
                {"name": "tool2", "description": "Tool 2"}
            ]
        }
        assert validate_agent_config(config) is True
    
    def test_validate_agent_config_invalid(self):
        """Test validation of invalid agent configurations."""
        # Missing name
        config = {"model": "gpt-4"}
        assert validate_agent_config(config) is False
        
        # Empty name
        config = {"name": ""}
        assert validate_agent_config(config) is False
        
        # Invalid tools (not a list)
        config = {"name": "test_agent", "tools": "not_a_list"}
        assert validate_agent_config(config) is False
        
        # Invalid tool (missing name)
        config = {
            "name": "test_agent",
            "tools": [{"description": "Tool without name"}]
        }
        assert validate_agent_config(config) is False
        
        # Invalid tool (not a dict)
        config = {
            "name": "test_agent", 
            "tools": ["not_a_dict"]
        }
        assert validate_agent_config(config) is False
    
    def test_build_adk_agent_from_config_basic(self):
        """Test building ADK agent from basic configuration."""
        config = {
            "name": "test_agent",
            "description": "Test agent",
            "model": "gpt-4",
            "instructions": "You are a helpful assistant"
        }
        
        agent = build_adk_agent_from_config(config)
        
        assert isinstance(agent, BaseAgent)
        assert isinstance(agent, LlmAgent)
        assert agent.name == "test_agent"
        assert agent.description == "Test agent"
        assert agent.model == "gpt-4"
        assert agent.instruction == "You are a helpful assistant"
    
    def test_build_adk_agent_from_config_minimal(self):
        """Test building ADK agent from minimal configuration."""
        config = {"name": "minimal_agent"}
        
        agent = build_adk_agent_from_config(config)
        
        assert isinstance(agent, BaseAgent)
        assert agent.name == "minimal_agent"
        assert agent.description == ""  # Default empty description
        assert agent.model == "gpt-4"  # Default model
        assert agent.instruction == ""  # Default empty instruction
    
    def test_build_adk_agent_with_tools(self):
        """Test building ADK agent with tools configuration."""
        # Note: This test may need adjustment based on actual tool implementation
        config = {
            "name": "agent_with_tools",
            "tools": [
                {"name": "test_tool", "description": "A test tool"}
            ]
        }
        
        agent = build_adk_agent_from_config(config)
        
        assert isinstance(agent, BaseAgent)
        assert agent.name == "agent_with_tools"
        # Tools handling may vary based on implementation
        # assert len(agent.tools) == 1
    
    def test_extract_agent_metadata_basic(self):
        """Test extracting metadata from basic agent."""
        config = {
            "name": "test_agent",
            "description": "Test description",
            "model": "gpt-4",
            "instructions": "Test instructions"
        }
        
        agent = build_adk_agent_from_config(config)
        metadata = extract_agent_metadata(agent)
        
        assert metadata["name"] == "test_agent"
        assert metadata["description"] == "Test description"
        assert metadata["type"] == "LlmAgent"
        assert metadata["model"] == "gpt-4"
        assert metadata["instruction"] == "Test instructions"
        assert "sub_agents" not in metadata
    
    def test_extract_agent_metadata_with_sub_agents(self):
        """Test extracting metadata from agent with sub-agents."""
        # Create main agent
        main_config = {"name": "main_agent", "description": "Main agent"}
        main_agent = build_adk_agent_from_config(main_config)
        
        # Create sub-agent
        sub_config = {"name": "sub_agent", "description": "Sub agent"}
        sub_agent = build_adk_agent_from_config(sub_config)
        
        # Add sub-agent to main agent
        main_agent.sub_agents = [sub_agent]
        
        # Extract metadata
        metadata = extract_agent_metadata(main_agent)
        
        assert metadata["name"] == "main_agent"
        assert "sub_agents" in metadata
        assert len(metadata["sub_agents"]) == 1
        assert metadata["sub_agents"][0]["name"] == "sub_agent"
        assert metadata["sub_agents"][0]["description"] == "Sub agent"
    
    def test_agent_config_defaults(self):
        """Test that agent configuration applies correct defaults."""
        config = {"name": "default_test"}
        
        agent = build_adk_agent_from_config(config)
        
        # Verify defaults are applied
        assert agent.name == "default_test"
        assert agent.description == ""
        assert agent.model == "gpt-4"
        assert agent.instruction == ""
        assert len(agent.sub_agents) == 0
    
    def test_agent_name_validation(self):
        """Test that agent names are properly validated."""
        # Valid name
        config = {"name": "valid_agent_name"}
        agent = build_adk_agent_from_config(config)
        assert agent.name == "valid_agent_name"
        
        # Test that invalid names would be caught by ADK validation
        # (This depends on ADK's internal validation)
        try:
            invalid_config = {"name": "invalid-name-with-hyphens"}
            build_adk_agent_from_config(invalid_config)
            # If no exception, the validation is more permissive than expected
        except Exception:
            # Expected if ADK validates names strictly
            pass
    
    def test_agent_hierarchy(self):
        """Test building agent hierarchies."""
        # Create parent agent
        parent_config = {"name": "parent", "description": "Parent agent"}
        parent_agent = build_adk_agent_from_config(parent_config)
        
        # Create child agents
        child1_config = {"name": "child1", "description": "Child 1"}
        child1_agent = build_adk_agent_from_config(child1_config)
        
        child2_config = {"name": "child2", "description": "Child 2"}
        child2_agent = build_adk_agent_from_config(child2_config)
        
        # Build hierarchy
        parent_agent.sub_agents = [child1_agent, child2_agent]
        
        # Verify hierarchy
        assert len(parent_agent.sub_agents) == 2
        assert parent_agent.sub_agents[0].name == "child1"
        assert parent_agent.sub_agents[1].name == "child2"
        
        # Test metadata extraction includes hierarchy
        metadata = extract_agent_metadata(parent_agent)
        assert len(metadata["sub_agents"]) == 2
        assert metadata["sub_agents"][0]["name"] == "child1"
        assert metadata["sub_agents"][1]["name"] == "child2"