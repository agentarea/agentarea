"""Test tool call extraction fix."""

import sys
sys.path.insert(0, "core")

from libs.execution.agentarea_execution.workflows.helpers import ToolCallExtractor
from libs.execution.agentarea_execution.workflows.agent_execution_workflow import Message, ToolCall

def test_tool_call_extraction():
    """Test that tool calls are properly extracted and converted to ToolCall objects."""
    
    # Simulate a message with tool calls (as would come from LLM activity)
    message = Message(
        role="assistant",
        content="I'll complete this task now.",
        tool_calls=[
            {
                "id": "call_123",
                "type": "function",
                "function": {
                    "name": "task_complete",
                    "arguments": '{"result": "Task completed successfully"}'
                }
            }
        ]
    )
    
    # Extract tool calls
    extracted_calls = ToolCallExtractor.extract_tool_calls(message)
    
    print(f"Extracted {len(extracted_calls)} tool calls")
    
    if extracted_calls:
        tool_call = extracted_calls[0]
        print(f"Tool call type: {type(tool_call)}")
        print(f"Tool call ID: {tool_call.id}")
        print(f"Tool call function: {tool_call.function}")
        print(f"Function name: {tool_call.function['name']}")
        print(f"Function arguments: {tool_call.function['arguments']}")
        
        # Verify it's a ToolCall object
        assert isinstance(tool_call, ToolCall), f"Expected ToolCall, got {type(tool_call)}"
        assert tool_call.id == "call_123", f"Expected call_123, got {tool_call.id}"
        assert tool_call.function["name"] == "task_complete", f"Expected task_complete, got {tool_call.function['name']}"
        
        print("✅ Tool call extraction test passed!")
        return True
    else:
        print("❌ No tool calls extracted!")
        return False

if __name__ == "__main__":
    success = test_tool_call_extraction()
    sys.exit(0 if success else 1)