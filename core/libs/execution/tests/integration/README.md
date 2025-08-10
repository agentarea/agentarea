# LLM Model Integration Tests

This directory contains integration tests for the LLM model implementation that test against real external services.

## Test Files

### `test_llm_model_integration.py`

Comprehensive integration tests for the `LLMModel` class with real Ollama instance running qwen2.5 model.

**Test Coverage:**
- ✅ Basic LLM completion without tools
- ✅ LLM completion with function tools
- ✅ Streaming completion with event publishing
- ✅ Error handling for invalid models
- ✅ Error handling for invalid endpoints
- ✅ Parameter validation (temperature, max_tokens)
- ✅ Concurrent request handling

## Prerequisites

### 1. Ollama Setup

You need Ollama running locally with the qwen2.5 model:

```bash
# Install Ollama (if not already installed)
curl -fsSL https://ollama.ai/install.sh | sh

# Start Ollama service
ollama serve

# Pull qwen2.5 model
ollama pull qwen2.5

# Verify installation
curl http://localhost:11434/api/tags
```

### 2. Python Dependencies

The tests use the existing project dependencies:
- `pytest`
- `pytest-asyncio`
- `litellm`
- The `agentarea_execution` module

## Running the Tests

### Run All Integration Tests

```bash
# From the core directory
cd /path/to/agentarea/core

# Run all LLM integration tests
python -m pytest libs/execution/tests/integration/test_llm_model_integration.py -v

# Run with detailed output
python -m pytest libs/execution/tests/integration/test_llm_model_integration.py -v -s
```

### Run Specific Tests

```bash
# Test basic completion
python -m pytest libs/execution/tests/integration/test_llm_model_integration.py::TestLLMModelIntegration::test_basic_completion -v

# Test streaming
python -m pytest libs/execution/tests/integration/test_llm_model_integration.py::TestLLMModelIntegration::test_streaming_completion -v

# Test tool calls
python -m pytest libs/execution/tests/integration/test_llm_model_integration.py::TestLLMModelIntegration::test_completion_with_tools -v
```

### Run with Integration Marker

```bash
# Run only integration tests (if markers are configured)
python -m pytest -m integration libs/execution/tests/integration/test_llm_model_integration.py -v
```

## Test Results Example

When running successfully, you should see output like:

```
✅ Test 1: Basic completion - Response: '4'
💰 Cost: $0.000380, 📊 Usage: 38 tokens

✅ Test 2: Tool calls - 1 tool call made: calculate({"expression": "15 * 7"})
💰 Cost: $0.001880, 📊 Usage: 188 tokens

✅ Test 3: Streaming - 40 chunks captured
📨 Chunks: 'AI, or artificial intelligence, is the simulation...'
💰 Cost: $0.000000, 📊 Usage: 0 tokens
```

## Troubleshooting

### Ollama Not Running

If you see:
```
pytest.skip: Ollama is not running on localhost:11434
```

**Solution:**
1. Start Ollama: `ollama serve`
2. Verify it's running: `curl http://localhost:11434/api/tags`

### Model Not Found

If you see:
```
pytest.skip: qwen2.5 model not found in Ollama
```

**Solution:**
1. Pull the model: `ollama pull qwen2.5`
2. Verify: `ollama list`

### Connection Errors

If you see connection timeouts or errors:

1. **Check Ollama status:**
   ```bash
   ps aux | grep ollama
   curl -v http://localhost:11434/api/tags
   ```

2. **Check port availability:**
   ```bash
   lsof -i :11434
   ```

3. **Restart Ollama:**
   ```bash
   pkill ollama
   ollama serve
   ```

### Import Errors

If you see module import errors:

1. **Ensure you're in the core directory:**
   ```bash
   cd /path/to/agentarea/core
   ```

2. **Check Python path:**
   ```bash
   python -c "import sys; print('\n'.join(sys.path))"
   ```

3. **Install dependencies:**
   ```bash
   uv sync
   ```

## Test Configuration

### Markers

The tests use the `@pytest.mark.integration` marker. To register this marker, add to `pytest.ini`:

```ini
[tool:pytest]
markers =
    integration: marks tests as integration tests (requiring real services)
```

### Timeouts

The tests include reasonable timeouts:
- Ollama availability check: 10 seconds
- Individual LLM calls: Default litellm timeout
- Streaming tests: Based on max_tokens

### Resource Cleanup

Note: You may see warnings about unclosed client sessions. These are from the underlying `litellm` library and don't affect test functionality.

## Adding New Tests

When adding new integration tests:

1. **Follow the existing pattern:**
   ```python
   @pytest.mark.asyncio
   async def test_new_feature(self, llm_model: LLMModel, check_ollama_availability):
       # Test implementation
   ```

2. **Use fixtures:**
   - `llm_model`: Pre-configured LLM model instance
   - `event_capture`: For streaming tests
   - `check_ollama_availability`: Ensures Ollama is running

3. **Include proper assertions:**
   - Verify response structure
   - Check cost and usage information
   - Validate error handling

4. **Add logging:**
   ```python
   logger.info(f"✅ Test result: {response.content}")
   ```

## Performance Notes

- **Test Duration:** Each test typically takes 2-5 seconds
- **Resource Usage:** Tests use minimal tokens to keep costs low
- **Concurrency:** Tests include concurrent request validation
- **Streaming:** Streaming tests verify chunk-by-chunk delivery

The integration tests provide confidence that the LLM model implementation works correctly with real Ollama instances and can handle various scenarios including error conditions.