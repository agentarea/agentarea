# Integration Tests

This directory contains the essential integration tests for AgentArea. These tests have been cleaned up to remove duplicates and focus on core functionality.

## Remaining Test Files

### Core E2E Tests
- **`test_e2e_main_flow.py`** - **PRIMARY E2E TEST**
  - Complete end-to-end flow: model → instance → agent → task → verification
  - Tests A2A protocol compliance and agent output verification
  - Includes proper task completion waiting and result validation
  - **This is the main integration test to run**

### Temporal Workflow Tests
- **`test_temporal_workflow_real_db.py`** - Tests workflows with real database
  - Tests actual AgentTaskWorkflow with real database connections
  - Uses real activities (not mocked)
  - Essential for testing real DB integration

- **`test_agent_task_workflow.py`** - Tests workflows with mocked activities
  - Unit-level testing of workflow components using Temporal testing framework
  - Tests workflow logic in isolation with mocked dependencies
  - Good for testing workflow behavior without external dependencies

### Protocol Tests
- **`test_protocol_endpoints.py`** - Tests A2A protocol endpoints
  - Tests both JSON-RPC and REST interfaces
  - Protocol-specific testing for agent discovery and communication
  - Complements the main E2E flow

### File Upload Tests
- **`test_presigned_url.py`** - Tests file upload functionality
  - Tests presigned URL generation and file upload flow
  - Specific feature testing not covered elsewhere

### Repository Tests (`repositories/`)
All repository tests are kept as they provide essential data layer testing:
- **`test_agent_repository.py`** - Agent CRUD operations
- **`test_llm_model_repository.py`** - LLM model CRUD operations  
- **`test_llm_model_instance_repository.py`** - LLM model instance CRUD operations
- **`test_mcp_server_repository.py`** - MCP server CRUD operations
- **`test_mcp_server_instance_repository.py`** - MCP server instance CRUD operations
- **`test_task_repository.py`** - Task CRUD operations
- **`test_task_repository_new.py`** - Updated task repository tests
- **`conftest.py`** - Shared fixtures for repository tests

## Removed Files (Duplicates/Obsolete)

The following files were removed as duplicates or non-essential:

1. **`test_e2e_working.py`** - Duplicate of main E2E test (less comprehensive)
2. **`comprehensive_e2e_test.py`** - Duplicate E2E test focusing on A2A protocol
3. **`test_temporal_integration.py`** - Duplicate temporal integration test
4. **`test_temporal_workflow_integration.py`** - Overlapped with real DB test
5. **`test_agent_runner_service_simple.py`** - Heavily mocked unit test (not integration)
6. **`test_temporal_connection.py`** - Simple connection test/diagnostic script

## Running the Tests

### Primary E2E Test
```bash
# Run the main end-to-end test
pytest tests/integration/test_e2e_main_flow.py -v

# Run specific test methods
pytest tests/integration/test_e2e_main_flow.py::TestE2EMainFlow::test_complete_flow_with_execution_verification -v
```

### Temporal Workflow Tests
```bash
# Real database workflow test
pytest tests/integration/test_temporal_workflow_real_db.py -v

# Mocked workflow test  
pytest tests/integration/test_agent_task_workflow.py -v
```

### Protocol Tests
```bash
# A2A protocol endpoints
pytest tests/integration/test_protocol_endpoints.py -v
```

### Repository Tests
```bash
# All repository tests
pytest tests/integration/repositories/ -v

# Specific repository
pytest tests/integration/repositories/test_agent_repository.py -v
```

### All Integration Tests
```bash
# Run all integration tests
pytest tests/integration/ -v
```

## Test Dependencies

These tests require:
- **Database**: PostgreSQL running and accessible
- **Redis**: For event broker (or will fallback to test broker)
- **Temporal**: Server running for workflow tests
- **Ollama**: For LLM integration tests (with qwen2.5:latest model)
- **AgentArea Service**: Running on localhost:8000

## Test Structure

Each test is designed to be:
- **Independent**: Can run in isolation
- **Comprehensive**: Tests complete workflows
- **Resilient**: Handles service unavailability gracefully
- **Informative**: Provides detailed output and error messages

The tests follow the pattern:
1. **Setup**: Create test data and dependencies
2. **Execute**: Run the actual workflow/functionality
3. **Verify**: Check results and side effects
4. **Cleanup**: Clean up test data (where applicable) 