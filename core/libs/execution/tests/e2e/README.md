# End-to-End Temporal Workflow Tests

This directory contains comprehensive end-to-end tests for AgentArea's Temporal workflow execution system. The tests validate complete workflow execution against real infrastructure without any mocks.

## 🎯 What This Tests

- **Real Infrastructure Integration**: Connects to actual Temporal server, PostgreSQL database, and Redis
- **Complete Workflow Execution**: Tests the full `AgentExecutionWorkflow` from start to finish
- **Service Dependency Injection**: Validates real AgentArea services through the DI container
- **Concurrent Execution**: Tests multiple workflows running simultaneously
- **Error Handling**: Validates proper error handling and recovery mechanisms
- **Database Operations**: Tests agent creation, memory persistence, and data consistency

## 🏗️ Architecture

```
E2E Test Framework
├── Infrastructure Checks
│   ├── Temporal Server (localhost:7233)
│   ├── PostgreSQL Database (localhost:5432)
│   └── Redis (localhost:6379)
├── Service Setup
│   ├── DI Container Initialization
│   ├── Real AgentArea Services
│   └── Activity Services Interface
├── Test Worker
│   ├── Temporary Temporal Worker
│   ├── Unique Task Queue
│   └── Real Activities Registration
└── Test Execution
    ├── Agent Configuration
    ├── Workflow Submission
    ├── Result Verification
    └── Cleanup
```

## 🚀 Quick Start

### Prerequisites

1. **Docker & Docker Compose**: For running infrastructure services
2. **AgentArea Environment**: Properly configured development environment
3. **Database Migrations**: Up-to-date database schema

### Option 1: Automated Setup (Recommended)

```bash
# Navigate to the E2E test directory
cd core/libs/execution/tests/e2e

# Run the automated test script
./run_e2e_test.sh

# Or run with pytest
./run_e2e_test.sh --pytest
```

### Option 2: Manual Setup

```bash
# 1. Start infrastructure services
docker-compose up -d temporal db redis

# 2. Wait for services to be ready
sleep 15

# 3. Run database migrations
cd core/apps/api
alembic upgrade head
cd -

# 4. Set environment variables
export POSTGRES_HOST="localhost"
export POSTGRES_PORT="5432"
export TEMPORAL_SERVER_URL="localhost:7233"
export TEMPORAL_NAMESPACE="default"
export APP_ENV="test"
export DEBUG="true"

# 5. Run the test
cd core/libs/execution/tests/e2e
python test_e2e_agent_workflow.py
```

## 🧪 Test Cases

### 1. Simple Query Execution
- **Purpose**: Basic workflow execution without tools
- **Validates**: Agent response generation, conversation history
- **Example Query**: "Hello! Can you introduce yourself?"

### 2. Reasoning Task Execution  
- **Purpose**: Complex reasoning and calculation tasks
- **Validates**: Multi-step reasoning, result accuracy
- **Example Query**: "What's 25 + 17? Please show your reasoning."

### 3. Multiple Concurrent Executions
- **Purpose**: Parallel workflow execution
- **Validates**: Worker scalability, resource isolation
- **Test**: 3 simultaneous workflows with different queries

### 4. Error Handling and Recovery
- **Purpose**: Graceful error handling
- **Validates**: Error reporting, workflow resilience
- **Test**: Challenging queries that may trigger edge cases

## 📊 Expected Output

### Successful Test Run
```
🚀 Starting E2E Temporal Workflow Test
============================================
🔧 Setting up E2E test infrastructure...
✅ Temporal server is available
✅ Database available with 2 agents
✅ Redis is available
✅ DI Container initialized with real services
✅ Connected to Temporal at localhost:7233
🚀 Starting test worker on task queue: e2e-test-abc123...
✅ Test worker started and ready
✅ Using existing test agent: def456-abc123-...

🧪 Test 1: Simple Query Execution
🎯 Starting workflow execution: e2e-test-task789...
✅ Workflow started: e2e-test-task789
✅ Workflow completed: e2e-test-task789
🔍 Verifying execution result...
✅ Workflow completed successfully
✅ Got final response: Hello! I'm an AI assistant...
✅ Conversation history: 2 messages
✅ Task and agent IDs present
✅ Execution metrics: 1 iterations, 0 tool calls
🎉 All result verifications passed!

🧪 Test 2: Reasoning Task
[... similar output ...]

🧪 Test 3: Concurrent Executions
[... similar output ...]

🎉 All E2E tests completed successfully!
============================================
📊 Test Summary:
   ✅ Simple query: True
   ✅ Reasoning task: True  
   ✅ Concurrent executions: 3 completed
   ✅ Real infrastructure: Temporal + DB + Redis
   ✅ Real services: Agent + MCP + LLM + Events
   ✅ No mocks: Complete end-to-end validation
```

## 🔍 Monitoring & Debugging

### Temporal UI
- **URL**: http://localhost:8233
- **View**: Workflow executions, activity details, errors
- **Filter**: Search by workflow ID or task queue name

### Database Inspection
```sql
-- Connect to database
psql -h localhost -U postgres -d aiagents

-- Check agents
SELECT id, name, status FROM agents LIMIT 5;

-- Check recent activity
SELECT * FROM agent_memory WHERE created_at > NOW() - INTERVAL '1 hour';
```

### Service Logs
```bash
# View all service logs
docker-compose logs -f temporal db redis

# View specific service
docker-compose logs -f temporal
```

## 🐛 Troubleshooting

### Common Issues

#### 1. Temporal Connection Failed
```
❌ Temporal server check failed: Connection refused
```
**Solution**: 
```bash
docker-compose up -d temporal
# Wait 30 seconds for startup
```

#### 2. Database Migration Issues
```
❌ Database check failed: relation "agents" does not exist
```
**Solution**:
```bash
cd core/apps/api
alembic upgrade head
```

#### 3. No Agents Found
```
⚠️ No agents found in database - some tests may fail
```
**Solution**: The test will automatically create a test agent, or you can create one manually:
```sql
INSERT INTO agents (id, name, description, instruction, status) 
VALUES (gen_random_uuid(), 'Test Agent', 'Test agent for E2E', 'You are helpful.', 'active');
```

#### 4. Worker Registration Issues
```
❌ Failed to register activities
```
**Solution**: Check that all imports are working and services are properly initialized.

### Debug Mode

For detailed debugging, run with debug logging:
```bash
export DEBUG=true
export LOG_LEVEL=DEBUG
python test_e2e_agent_workflow.py
```

## 🔧 Configuration

### Environment Variables
- `POSTGRES_HOST`: Database host (default: localhost)
- `POSTGRES_PORT`: Database port (default: 5432) 
- `TEMPORAL_SERVER_URL`: Temporal server URL (default: localhost:7233)
- `TEMPORAL_NAMESPACE`: Temporal namespace (default: default)
- `APP_ENV`: Application environment (default: test)
- `DEBUG`: Enable debug logging (default: true)

### Test Customization

To modify test behavior, edit `test_e2e_agent_workflow.py`:

```python
# Adjust timeouts
request = AgentExecutionRequest(
    timeout_seconds=600,  # Increase timeout
    max_reasoning_iterations=5,  # More iterations
)

# Change test queries
test_queries = [
    "Your custom test query here",
    "Another test query",
]
```

## 📈 Performance Metrics

The test tracks several metrics:
- **Setup Time**: Infrastructure connection and worker startup
- **Execution Time**: Individual workflow execution duration  
- **Throughput**: Concurrent workflow processing capacity
- **Resource Usage**: Memory and CPU utilization during tests

## 🤝 Contributing

When adding new test cases:

1. **Follow the Pattern**: Use the existing `E2ETemporalTest` framework
2. **Validate Results**: Always verify both success and failure scenarios
3. **Clean Up**: Ensure proper resource cleanup in test teardown
4. **Document**: Add clear descriptions of what each test validates

### Example New Test
```python
@pytest.mark.asyncio
async def test_custom_scenario(self, e2e_test: E2ETemporalTest, test_agent_id: UUID):
    """Test custom workflow scenario."""
    test_query = "Your custom test scenario"
    
    result = await e2e_test.execute_workflow_test(test_agent_id, test_query)
    await e2e_test.verify_execution_result(result, test_query)
    
    # Custom validations
    assert "expected_content" in result.final_response
```

## 📚 Related Documentation

- [Temporal Workflow Implementation](../../workflows/README.md)
- [AgentArea Architecture](../../../../docs/architecture.md)
- [Activity Development Guide](../../activities/README.md)
- [Integration Test Strategy](../../../tests/integration/README.md) 