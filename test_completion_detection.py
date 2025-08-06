"""Test completion detection logic."""

import sys
import json
sys.path.insert(0, "core")

from libs.execution.agentarea_execution.agentic.tools.completion_tool import CompletionTool

async def test_completion_tool():
    """Test that the completion tool returns the expected result."""
    
    tool = CompletionTool()
    
    # Test with proper arguments
    result = await tool.execute(result="Task completed successfully")
    
    print(f"Completion tool result: {result}")
    print(f"Success: {result.get('success')}")
    print(f"Result: {result.get('result')}")
    print(f"Completed: {result.get('completed')}")
    
    # Verify the result structure
    assert result.get("success") == True, f"Expected success=True, got {result.get('success')}"
    assert result.get("completed") == True, f"Expected completed=True, got {result.get('completed')}"
    assert result.get("result") == "Task completed successfully", f"Expected specific result, got {result.get('result')}"
    
    print("✅ Completion tool test passed!")
    return True

def test_json_parsing():
    """Test JSON argument parsing."""
    
    # Simulate the JSON string that comes from LLM
    json_args = '{"result": "Task completed successfully"}'
    
    try:
        parsed_args = json.loads(json_args)
        print(f"Parsed args: {parsed_args}")
        print(f"Result value: {parsed_args.get('result')}")
        
        assert isinstance(parsed_args, dict), f"Expected dict, got {type(parsed_args)}"
        assert parsed_args.get("result") == "Task completed successfully", f"Expected specific result, got {parsed_args.get('result')}"
        
        print("✅ JSON parsing test passed!")
        return True
    except Exception as e:
        print(f"❌ JSON parsing failed: {e}")
        return False

if __name__ == "__main__":
    import asyncio
    
    print("Testing completion detection logic...")
    
    # Test JSON parsing
    json_success = test_json_parsing()
    
    # Test completion tool
    tool_success = asyncio.run(test_completion_tool())
    
    if json_success and tool_success:
        print("\n🎉 All tests passed! Completion detection should work correctly.")
        sys.exit(0)
    else:
        print("\n❌ Some tests failed.")
        sys.exit(1)