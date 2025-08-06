# Trigger System Integration Tests

This directory contains comprehensive integration tests for the trigger system, covering all aspects of trigger creation, execution, lifecycle management, safety mechanisms, and performance validation.

## Test Structure

### 1. End-to-End Scenarios (`test_trigger_e2e_scenarios.py`)
- Complete trigger workflows from creation to task execution
- API integration testing
- Multi-trigger coordination scenarios
- Error handling and recovery testing

### 2. Webhook HTTP Integration (`test_trigger_webhook_http_integration.py`)
- Real HTTP request processing for webhook triggers
- Different webhook types (GitHub, Slack, Telegram, Generic)
- Request validation and parsing
- Concurrent webhook request handling

### 3. Lifecycle Management (`test_trigger_lifecycle_management.py`)
- Trigger creation, update, enable/disable, and deletion
- State transitions and persistence
- Concurrent lifecycle operations
- Schedule management integration

### 4. Safety Mechanisms (`test_trigger_safety_integration.py`)
- Auto-disable functionality after consecutive failures
- Failure count tracking and reset
- Safety status monitoring
- Recovery mechanisms

### 5. Performance & Concurrency (`test_trigger_performance_concurrent.py`)
- Concurrent trigger execution testing
- High-throughput webhook processing
- Stress testing under load
- Memory and resource usage validation

### 6. Comprehensive Suite (`test_trigger_comprehensive_suite.py`)
- System health validation
- Component integration testing
- Data consistency verification
- Configuration validation
- Monitoring and observability testing

## Running the Tests

### Run All Integration Tests
```bash
# From the project root
python core/tests/run_trigger_integration_tests.py
```

### Run Specific Test Categories
```bash
# End-to-end scenarios
pytest core/tests/integration/test_trigger_e2e_scenarios.py -v

# Webhook integration
pytest core/tests/integration/test_trigger_webhook_http_integration.py -v

# Lifecycle management
pytest core/tests/integration/test_trigger_lifecycle_management.py -v

# Safety mechanisms
pytest core/tests/integration/test_trigger_safety_integration.py -v

# Performance tests
pytest core/tests/integration/test_trigger_performance_concurrent.py -v

# Comprehensive suite
pytest core/tests/integration/test_trigger_comprehensive_suite.py -v
```

### Run with Coverage
```bash
pytest core/tests/integration/test_trigger_*.py --cov=agentarea_triggers --cov-report=html
```

## Test Requirements

### Dependencies
- pytest
- pytest-asyncio
- httpx (for HTTP testing)
- FastAPI TestClient
- SQLAlchemy with async support

### Database Setup
Tests use an in-memory SQLite database by default. For PostgreSQL testing:
```bash
# Ensure PostgreSQL is running
docker run -d --name test-postgres -e POSTGRES_PASSWORD=postgres -p 5432:5432 postgres:13

# Run tests with PostgreSQL
POSTGRES_URL=postgresql://postgres:postgres@localhost:5432/test pytest core/tests/integration/test_trigger_*.py
```

### Mock Services
Tests use mocked versions of:
- TaskService (for task creation)
- EventBroker (for event publishing)
- TemporalScheduleManager (for cron scheduling)
- AgentRepository (for agent validation)

## Test Coverage Areas

### Functional Testing
- ✅ Trigger creation and validation
- ✅ Cron trigger scheduling
- ✅ Webhook trigger processing
- ✅ Condition evaluation
- ✅ Task parameter building
- ✅ Execution history tracking

### Integration Testing
- ✅ API endpoint integration
- ✅ Database persistence
- ✅ Event publishing
- ✅ Service dependencies
- ✅ Error propagation

### Safety & Reliability
- ✅ Auto-disable mechanisms
- ✅ Failure tracking
- ✅ Recovery procedures
- ✅ Data consistency
- ✅ Concurrent access safety

### Performance Testing
- ✅ Concurrent execution handling
- ✅ High-throughput processing
- ✅ Memory usage validation
- ✅ Database connection management
- ✅ Response time validation

## Expected Test Results

### Performance Benchmarks
- Single trigger execution: < 1 second
- Concurrent executions (10): < 5 seconds
- Webhook processing: < 2 seconds per request
- High-throughput: > 5 requests/second
- System throughput: > 2 operations/second

### Reliability Metrics
- Test success rate: > 95%
- Auto-disable accuracy: 100%
- Data consistency: 100%
- Error recovery: 100%

## Troubleshooting

### Common Issues

1. **Import Errors**
   ```
   ImportError: No module named 'agentarea_triggers'
   ```
   - Ensure trigger system is properly installed
   - Check PYTHONPATH includes core directory

2. **Database Connection Issues**
   ```
   sqlalchemy.exc.OperationalError: (sqlite3.OperationalError) no such table
   ```
   - Ensure database migrations are applied
   - Check test database setup

3. **Async Test Issues**
   ```
   RuntimeError: There is no current event loop
   ```
   - Ensure pytest-asyncio is installed
   - Use `@pytest.mark.asyncio` decorator

4. **Mock Service Issues**
   ```
   AttributeError: Mock object has no attribute 'create_task_from_params'
   ```
   - Check mock service setup in fixtures
   - Verify mock return values are configured

### Debug Mode
Run tests with debug output:
```bash
pytest core/tests/integration/test_trigger_*.py -v -s --log-cli-level=DEBUG
```

### Performance Profiling
Profile test execution:
```bash
pytest core/tests/integration/test_trigger_performance_concurrent.py --profile
```

## Contributing

When adding new integration tests:

1. Follow the existing test structure and naming conventions
2. Use appropriate fixtures for setup and teardown
3. Include both positive and negative test cases
4. Add performance assertions where relevant
5. Document any special requirements or setup
6. Update this README with new test categories

## Test Data Cleanup

Tests automatically clean up:
- Database records (via transaction rollback)
- Mock service state
- Temporary files
- Event broker messages

No manual cleanup is required between test runs.