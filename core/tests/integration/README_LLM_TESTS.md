# LLM Integration Tests

This directory contains comprehensive tests for LLM integration with ollama_chat/qwen2.5.

## Test Files

### `test_llm_response_parser.py`
**Purpose**: Test the complete LLM integration pipeline including response parsing and event publishing.

**Tests**:
- **`test_llm_with_structured_tools()`**: Tests LLM behavior when tools are provided - should return structured tool_calls
- **`test_llm_content_based_responses()`**: Tests LLM behavior without tools - should return JSON in content field  
- **`test_llm_streaming()`**: Tests streaming LLM responses with event capture
- **`test_response_parser_with_different_formats()`**: Tests our `LiteLLMResponseParser` with both response formats
- **`test_react_framework_issue()`**: Tests the ReAct framework issue where LLM jumps to tool calls without reasoning

**Key Findings**:
1. **Two Response Modes**: 
   - With tools: Empty content + structured tool_calls
   - Without tools: JSON content + no tool_calls  
2. **Parser Works**: Handles both formats correctly
3. **Streaming Works**: Captures chunk events properly
4. **ReAct Issue**: Identifies when LLM skips reasoning step

### `test_react_framework_behavior.py`
**Purpose**: Specifically test ReAct framework behavior and tool_choice configurations.

**Tests**:
- **`test_react_framework_natural_response()`**: Tests if LLM provides reasoning before tool calls
- **`test_tool_choice_configurations()`**: Tests different tool_choice settings (auto, none, required)

**Issue Identified**: 
When using tools with `tool_choice: "auto"`, qwen2.5 sometimes jumps directly to tool calls without providing the expected reasoning content first. This breaks the ReAct framework pattern.

## Prerequisites

1. **Ollama Running**: `ollama serve` on localhost:11434
2. **qwen2.5 Model**: `ollama pull qwen2.5`
3. **Dependencies**: All AgentArea dependencies installed

## Running Tests

```bash
# Run all LLM integration tests
pytest tests/integration/test_llm_response_parser.py -v

# Run specific test
pytest tests/integration/test_llm_response_parser.py::test_llm_streaming -v

# Run ReAct framework tests as pytest
pytest tests/integration/test_react_framework_behavior.py -v

# Run tests directly for debugging
python tests/integration/test_llm_response_parser.py
python tests/integration/test_react_framework_behavior.py
```

## Expected Results

All tests should pass when:
- ✅ Ollama is running with qwen2.5
- ✅ LLM responds appropriately to different configurations  
- ✅ Response parser extracts tool calls from both formats
- ✅ Streaming events are captured correctly

## Test Output Analysis

### Successful Response Formats

**With Tools (Structured)**:
```json
{
  "content": "",  
  "tool_calls": [{
    "id": "befc1a24-...",
    "type": "function", 
    "function": {
      "name": "task_complete",
      "arguments": "{\"result\": \"Task completed successfully.\"}"
    }
  }]
}
```

**Without Tools (Content-based)**:
```json
{
  "content": "{\"name\": \"task_complete\", \"arguments\": {\"result\": \"Task completed.\"}}",
  "tool_calls": null
}
```

### Streaming Events
```
📨 Chunk Event: index=0, final=False, chunk='Task'
📨 Chunk Event: index=1, final=False, chunk=' completion'
...
📨 Chunk Event: index=362, final=True, chunk=''
```

## Common Issues

### 1. ReAct Framework Immediate Tool Calls
**Problem**: LLM calls tools immediately without reasoning
**Cause**: `tool_choice: "auto"` may force tool usage
**Solution**: Use `tool_choice: "none"` or adjust system prompt

### 2. Module Import Errors  
**Problem**: `ModuleNotFoundError: No module named 'libs'`
**Cause**: Running test outside proper Python path
**Solution**: Run from core directory with proper PYTHONPATH

### 3. Ollama Connection Issues
**Problem**: Connection refused to localhost:11434
**Cause**: Ollama not running or wrong port
**Solution**: Start Ollama with `ollama serve`

## Integration with Workflow Tests

These tests complement the existing workflow tests:
- `test_workflow_integration.py` - End-to-end workflow execution
- `test_temporal_workflow.py` - Temporal-specific workflow testing  
- `test_agent_task_workflow.py` - Agent task execution

The LLM tests focus specifically on the LLM interaction layer, ensuring the foundation works correctly before testing full workflow orchestration.

## Debugging Tips

1. **Enable Detailed Logging**: Set `logging.basicConfig(level=logging.DEBUG)`
2. **Check Response Content**: Log `repr(response.content)` to see exact format
3. **Monitor Events**: Use EventCapture class to see streaming behavior
4. **Test Configurations**: Try different tool_choice and temperature settings
5. **Validate JSON**: Check if content-based responses are valid JSON

## Future Enhancements

1. **Multiple Models**: Test with other Ollama models (llama2, mistral)
2. **Error Scenarios**: Test network failures, invalid responses  
3. **Performance Testing**: Measure response times and costs
4. **Real Workflow Integration**: Connect to actual workflow execution
5. **Tool Choice Optimization**: Find best configuration for ReAct framework