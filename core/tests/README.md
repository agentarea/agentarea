# Testing Guide

## Quick Commands

```bash
# 🧪 Run all working tests (49 tests)
python -m pytest tests/integration/repositories/ -k 'not task and not old' --tb=no -q

# 📊 Detailed test results
python -m pytest tests/integration/repositories/ -k 'not task and not old' --tb=short -v

# 🎯 Test specific repository
python -m pytest tests/integration/repositories/test_agent_repository.py -v
python -m pytest tests/integration/repositories/test_llm_model_repository.py -v
python -m pytest tests/integration/repositories/test_llm_model_instance_repository.py -v
python -m pytest tests/integration/repositories/test_mcp_server_repository.py -v
python -m pytest tests/integration/repositories/test_mcp_server_instance_repository.py -v
```

## Standard Commands (via pyproject.toml)

After `pip install -e .`:

```bash
test-quick        # Quick run (49 tests passing)
test-integration  # Detailed integration tests
test-unit         # Unit tests only
test              # All repository tests
dev               # Start development server
```

## Repository Status

✅ **Working (49 tests passing):**
- AgentRepository (6 tests)
- LLMModelRepository (10 tests)
- LLMModelInstanceRepository (11 tests)
- MCPServerRepository (12 tests)
- MCPServerInstanceRepository (10 tests)

❌ **Broken (needs fix):**
- TaskRepository (requires SQLAlchemy model implementation) 