"""Test malformed tool call extraction."""

import pytest
from agentarea_agents_sdk.models.llm_model import LLMModel


def test_extract_malformed_tool_calls_pattern1():
    """Test extraction of malformed tool calls with action/name pattern."""
    llm = LLMModel("test", "test")

    content = '''I need to complete this task.

{   "action": {     "name": "task_complete"   },   "arguments": {"result": "Task completed successfully"} }undefined

The task is now done.'''

    tool_calls, cleaned_content = llm._extract_malformed_tool_calls(content)

    assert tool_calls is not None
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "task_complete"
    assert '"result": "Task completed successfully"' in tool_calls[0]["function"]["arguments"]
    assert "undefined" not in cleaned_content
    assert "action" not in cleaned_content
    assert "I need to complete this task." in cleaned_content
    assert "The task is now done." in cleaned_content


def test_extract_malformed_tool_calls_pattern2():
    """Test extraction of malformed tool calls with name/arguments pattern."""
    llm = LLMModel("test", "test")

    content = '''{"name": "task_complete", "arguments": {"result": "I have not completed the task yet as I am still in the process of understanding who I am according to the given context."}}undefined'''

    tool_calls, cleaned_content = llm._extract_malformed_tool_calls(content)

    assert tool_calls is not None
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "task_complete"
    assert "I have not completed the task yet" in tool_calls[0]["function"]["arguments"]
    assert "undefined" not in cleaned_content
    assert cleaned_content.strip() == ""


def test_extract_malformed_tool_calls_empty_args():
    """Test extraction with empty arguments."""
    llm = LLMModel("test", "test")

    content = '''{   "action": {     "name": "task_complete"   },   "arguments": {} }undefined'''

    tool_calls, cleaned_content = llm._extract_malformed_tool_calls(content)

    assert tool_calls is not None
    assert len(tool_calls) == 1
    assert tool_calls[0]["function"]["name"] == "task_complete"
    assert tool_calls[0]["function"]["arguments"] == "{}"
    assert cleaned_content.strip() == ""


def test_extract_malformed_tool_calls_no_match():
    """Test that normal content without malformed tool calls is unchanged."""
    llm = LLMModel("test", "test")

    content = "This is normal content without any tool calls."

    tool_calls, cleaned_content = llm._extract_malformed_tool_calls(content)

    assert tool_calls is None
    assert cleaned_content == content


def test_extract_malformed_tool_calls_multiple():
    """Test extraction of multiple malformed tool calls."""
    llm = LLMModel("test", "test")

    content = '''First I'll do this:
{   "action": {     "name": "search"   },   "arguments": {"query": "test"} }

Then I'll complete:
{"name": "task_complete", "arguments": {"result": "Done"}}undefined'''

    tool_calls, cleaned_content = llm._extract_malformed_tool_calls(content)

    assert tool_calls is not None
    assert len(tool_calls) == 2
    assert tool_calls[0]["function"]["name"] == "search"
    assert tool_calls[1]["function"]["name"] == "task_complete"
    assert "First I'll do this:" in cleaned_content
    assert "Then I'll complete:" in cleaned_content
    assert "action" not in cleaned_content
    assert "undefined" not in cleaned_content


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
