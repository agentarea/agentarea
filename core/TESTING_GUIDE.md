# Testing Guide for Workflow Activities & Task Events

This guide explains how to test the new TaskEvent functionality and workflow activities that replace direct database access in Temporal activities.

## 🧪 Test Structure

### Unit Tests
- **`test_basic_functionality.py`** - Basic domain model tests
- **`test_task_event_service.py`** - TaskEventService business logic tests
- **`test_workflow_activities.py`** - Workflow activity tests with mocking

### Integration Tests
- **`test_task_event_integration.py`** - End-to-end database integration tests

## 🚀 Running Tests

### Quick Test Run
```bash
# Run basic functionality tests
uv run pytest tests/unit/test_basic_functionality.py -v

# Run all unit tests
uv run pytest tests/unit/ -v

# Run with coverage
uv run pytest tests/unit/ --cov=agentarea_tasks --cov=agentarea_execution
```

### Using the Test Runner
```bash
# Run the comprehensive test suite
python run_tests.py
```

### Individual Test Categories
```bash
# Test TaskEvent domain models
uv run pytest tests/unit/test_basic_functionality.py -v

# Test TaskEventService
uv run pytest tests/unit/test_task_event_service.py -v

# Test workflow activities
uv run pytest tests/unit/test_workflow_activities.py -v

# Test database integration (requires test DB)
uv run pytest tests/integration/test_task_event_integration.py -v
```

## 📋 Test Coverage

### Domain Models (`TaskEvent`)
- ✅ Model creation and validation
- ✅ Factory method (`create_workflow_event`)
- ✅ JSON serialization
- ✅ Default value handling
- ✅ Field validation

### Service Layer (`TaskEventService`)
- ✅ Event creation with proper dependencies
- ✅ Event retrieval by task ID
- ✅ Event retrieval by type
- ✅ Batch event creation
- ✅ Error handling and logging
- ✅ Repository interaction

### Repository Layer (`TaskEventRepository`)
- ✅ Database persistence
- ✅ Workspace isolation
- ✅ Query filtering
- ✅ ORM to domain model conversion

### Activities (`publish_workflow_events_activity`)
- ✅ Successful event publishing
- ✅ Redis event broker integration
- ✅ Database persistence via service
- ✅ Error handling (JSON parsing, DB errors, Redis errors)
- ✅ Empty event list handling

### Activities (`call_llm_activity`)
- ✅ Successful LLM calls
- ✅ Model validation
- ✅ Error handling
- ✅ Response formatting

## 🎯 Key Test Scenarios

### 1. **Event Creation Flow**
```python
# Test that events are created properly through the service
task_event_service = TaskEventService(repository_factory, event_broker)
event = await task_event_service.create_workflow_event(
    task_id=uuid4(),
    event_type="LLMCallStarted",
    data={"model": "gpt-4"},
    workspace_id="test-workspace"
)
```

### 2. **Activity Integration**
```python
# Test that activities use the service instead of raw SQL
result = await publish_workflow_events_activity(events_json)
assert result is True
# Verify service was called, not direct DB access
```

### 3. **Error Handling**
```python
# Test graceful error handling
mock_service.create_workflow_event.side_effect = Exception("DB Error")
result = await publish_workflow_events_activity(events_json)
# Should handle error gracefully and continue processing
```

### 4. **Workspace Isolation**
```python
# Test that events are properly isolated by workspace
workspace1_events = await repo1.get_events_for_task(task_id)
workspace2_events = await repo2.get_events_for_task(task_id)
assert len(workspace1_events) != len(workspace2_events)
```

## 🔧 Test Configuration

### Dependencies
- `pytest` - Test framework
- `pytest-asyncio` - Async test support
- `unittest.mock` - Mocking framework

### Fixtures
- `mock_event_broker` - Mock Redis event broker
- `mock_secret_manager` - Mock secret manager
- `mock_repository_factory` - Mock repository factory
- `db_session` - Test database session (integration tests)

### Environment
- Tests use mocked dependencies by default
- Integration tests require a test database
- All tests are isolated and can run in parallel

## 📊 Test Results

When you run the tests, you should see output like:

```
✅ test_task_event_creation PASSED
✅ test_task_event_factory_method PASSED
✅ test_create_workflow_event_success PASSED
✅ test_publish_workflow_events_success PASSED
✅ test_workspace_isolation PASSED

5 passed, 0 failed
```

## 🐛 Debugging Tests

### Common Issues
1. **Import Errors**: Make sure all modules are properly installed
2. **Mock Issues**: Verify mock setup matches actual interfaces
3. **Async Issues**: Use `pytest.mark.asyncio` for async tests
4. **Database Issues**: Check database connection for integration tests

### Debug Commands
```bash
# Run with verbose output and stop on first failure
uv run pytest tests/unit/test_task_event_service.py -v -x

# Run with pdb debugger
uv run pytest tests/unit/test_task_event_service.py --pdb

# Run specific test method
uv run pytest tests/unit/test_task_event_service.py::TestTaskEventService::test_create_workflow_event_success -v
```

## ✅ Verification Checklist

After running tests, verify:

- [ ] All domain models work correctly
- [ ] Service layer properly abstracts database access
- [ ] Activities use services instead of raw SQL
- [ ] Error handling works gracefully
- [ ] Workspace isolation is maintained
- [ ] Event publishing works end-to-end
- [ ] Integration with existing systems is preserved

## 🎉 Success Criteria

The tests verify that:

1. **No Direct Database Access** in activities
2. **Proper Domain Architecture** with models, services, and repositories
3. **Error Handling** that doesn't break workflows
4. **Workspace Isolation** for multi-tenancy
5. **Event Publishing** works reliably
6. **Backward Compatibility** is maintained

This testing suite ensures the refactored code is production-ready and follows best practices!