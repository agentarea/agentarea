# Multi-Agent Execution Design & Testing Strategy

## 🎯 Executive Summary

This document outlines the architecture for **agent-calling-other-agents scenarios** and comprehensive testing strategies for our Google ADK-powered execution system.

## 🏗️ Multi-Agent Architecture Decision

### **Recommendation: Child Workflows Pattern**

For agent-calling-other-agents scenarios, we recommend using **Temporal Child Workflows**:

```python
# Parent Agent Workflow
@workflow.defn
class AgentExecutionWorkflow:
    @workflow.run
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        # ... normal agent execution ...
        
        # If agent needs to call another agent:
        if needs_other_agent:
            child_request = AgentExecutionRequest(...)
            
            # Start child workflow for sub-agent
            child_result = await workflow.execute_child_workflow(
                AgentExecutionWorkflow.run,
                child_request,
                id=f"child-agent-{child_request.task_id}",
                task_queue="agent-execution",
            )
            
            # Continue with parent agent using child result
            return self.combine_results(parent_result, child_result)
```

### **Why Child Workflows vs Alternatives?**

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Child Workflows** ✅ | Independent lifecycle, observability, retry mechanisms, can run in parallel | Slightly more complex setup | **Recommended** |
| **Activities** | Simple implementation | No independent lifecycle, harder to observe, limited retry options | Not recommended |
| **Separate Workflows** | Complete independence | Hard to coordinate, no parent-child relationship | Complex |

### **Benefits of Child Workflows**

1. **Independent Lifecycle**: Each agent execution has its own workflow instance
2. **Observability**: Each agent execution is visible in Temporal UI
3. **Error Handling**: Child workflows can fail independently without affecting parent
4. **Parallel Execution**: Multiple child agents can run simultaneously
5. **Retry Mechanisms**: Each child workflow has its own retry configuration
6. **Resource Management**: Child workflows can be scheduled on different task queues

## 🧪 Testing Strategy (Based on Temporal Best Practices)

### **1. Integration Tests (Recommended Primary Approach)**

Following Temporal's recommendation to write **majority of tests as integration tests**:

```python
@pytest.mark.asyncio
async def test_multi_agent_execution():
    """Test agent calling another agent via child workflow."""
    async with WorkflowEnvironment() as env:
        # Mock successful parent agent execution
        async def mock_parent_execution(request, available_tools, activity_services):
            # Parent agent decides to call child agent
            child_request = AgentExecutionRequest(
                task_id=uuid4(),
                agent_id=uuid4(),  # Different agent
                user_id=request.user_id,
                task_query="Analyze the tourism impact of the weather data",
                parent_task_id=request.task_id,  # Link to parent
            )
            
            # Execute child workflow
            child_result = await workflow.execute_child_workflow(
                AgentExecutionWorkflow.run,
                child_request,
                id=f"child-{child_request.task_id}",
                task_queue="agent-execution",
            )
            
            return {
                "success": True,
                "final_response": f"Weather analysis complete. Tourism impact: {child_result.final_response}",
                "child_executions": [child_result],
                "conversation_history": [...],
            }
        
        # Create worker with mocked activities
        worker = Worker(
            env.client,
            task_queue="agent-execution",
            workflows=[AgentExecutionWorkflow],
            activities=[mock_parent_execution],
        )
        
        async with worker:
            result = await env.client.execute_workflow(
                AgentExecutionWorkflow.run,
                parent_request,
                id=f"multi-agent-test-{parent_request.task_id}",
                task_queue="agent-execution",
                execution_timeout=timedelta(minutes=10),
            )
            
            # Verify multi-agent execution
            assert result.success is True
            assert "tourism impact" in result.final_response.lower()
            assert len(result.child_executions) == 1
```

### **2. Unit Tests for Activities**

```python
@pytest.mark.asyncio
async def test_agent_coordination_activity():
    """Test activity that coordinates multiple agents."""
    coordinator_request = AgentCoordinationRequest(
        primary_agent_id=uuid4(),
        secondary_agents=[uuid4(), uuid4()],
        coordination_strategy="sequential",
    )
    
    result = await coordinate_multi_agent_execution_activity(
        coordinator_request, mock_services
    )
    
    assert result["success"] is True
    assert len(result["agent_results"]) == 3  # 1 primary + 2 secondary
```

### **3. End-to-End Tests**

```python
@pytest.mark.asyncio
@pytest.mark.e2e
async def test_real_multi_agent_workflow():
    """Test complete multi-agent execution with real Temporal server."""
    try:
        client = await Client.connect("localhost:7233")
        
        # Create realistic multi-agent request
        request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            user_id="test_user",
            task_query="Research weather in NYC, then analyze impact on tourism, then create a report",
            max_reasoning_iterations=15,
            timeout_seconds=900,  # 15 minutes
        )
        
        # Execute with real agents
        result = await client.execute_workflow(
            AgentExecutionWorkflow.run,
            request,
            id=f"e2e-multi-agent-{request.task_id}",
            task_queue="agent-execution",
            execution_timeout=timedelta(minutes=20),
        )
        
        # Verify complete execution
        assert result.success is True
        assert "weather" in result.final_response.lower()
        assert "tourism" in result.final_response.lower()
        assert "report" in result.final_response.lower()
        
    except Exception as e:
        pytest.skip(f"Real Temporal server not available: {e}")
```

### **4. Time-Skipping Tests**

```python
@pytest.mark.asyncio
async def test_multi_agent_timeout_handling():
    """Test timeout handling in multi-agent scenarios."""
    async with WorkflowEnvironment() as env:
        # Mock slow child agent
        async def slow_child_agent(request, available_tools, activity_services):
            await asyncio.sleep(600)  # 10 minutes (skipped in test)
            return {"success": True, "final_response": "Slow response"}
        
        # Test timeout behavior
        with pytest.raises(TimeoutError):
            await env.client.execute_workflow(
                AgentExecutionWorkflow.run,
                request,
                id=f"timeout-test-{request.task_id}",
                task_queue="agent-execution",
                execution_timeout=timedelta(minutes=5),  # Shorter than child execution
            )
```

## 🔄 Multi-Agent Execution Patterns

### **1. Sequential Multi-Agent Execution**

```python
@workflow.defn
class SequentialMultiAgentWorkflow:
    @workflow.run
    async def run(self, request: MultiAgentRequest) -> MultiAgentResult:
        results = []
        
        # Execute agents sequentially
        for agent_id in request.agent_sequence:
            child_request = AgentExecutionRequest(
                task_id=uuid4(),
                agent_id=agent_id,
                user_id=request.user_id,
                task_query=self.build_query_for_agent(agent_id, results),
                context={"previous_results": results},
            )
            
            child_result = await workflow.execute_child_workflow(
                AgentExecutionWorkflow.run,
                child_request,
                id=f"sequential-{agent_id}-{child_request.task_id}",
                task_queue="agent-execution",
            )
            
            results.append(child_result)
        
        return MultiAgentResult(
            success=all(r.success for r in results),
            agent_results=results,
            final_response=self.combine_responses(results),
        )
```

### **2. Parallel Multi-Agent Execution**

```python
@workflow.defn
class ParallelMultiAgentWorkflow:
    @workflow.run
    async def run(self, request: MultiAgentRequest) -> MultiAgentResult:
        # Start all child workflows in parallel
        child_futures = []
        
        for agent_id in request.agent_ids:
            child_request = AgentExecutionRequest(
                task_id=uuid4(),
                agent_id=agent_id,
                user_id=request.user_id,
                task_query=request.task_query,
            )
            
            future = workflow.execute_child_workflow(
                AgentExecutionWorkflow.run,
                child_request,
                id=f"parallel-{agent_id}-{child_request.task_id}",
                task_queue="agent-execution",
            )
            
            child_futures.append(future)
        
        # Wait for all to complete
        results = await asyncio.gather(*child_futures)
        
        return MultiAgentResult(
            success=all(r.success for r in results),
            agent_results=results,
            final_response=self.combine_responses(results),
        )
```

### **3. Coordinator-Agent Pattern**

```python
@workflow.defn
class CoordinatorAgentWorkflow:
    @workflow.run
    async def run(self, request: AgentExecutionRequest) -> AgentExecutionResult:
        # Coordinator agent analyzes the task
        coordinator_result = await workflow.execute_activity(
            execute_agent_task_activity,
            request,
            [],  # No tools needed for coordination
            activity_services,
            start_to_close_timeout=timedelta(minutes=5),
        )
        
        # Parse coordinator's plan
        execution_plan = self.parse_execution_plan(coordinator_result.final_response)
        
        # Execute sub-agents based on plan
        sub_results = []
        for sub_task in execution_plan.sub_tasks:
            sub_request = AgentExecutionRequest(
                task_id=uuid4(),
                agent_id=sub_task.agent_id,
                user_id=request.user_id,
                task_query=sub_task.query,
                parent_task_id=request.task_id,
            )
            
            sub_result = await workflow.execute_child_workflow(
                AgentExecutionWorkflow.run,
                sub_request,
                id=f"sub-{sub_task.agent_id}-{sub_request.task_id}",
                task_queue="agent-execution",
            )
            
            sub_results.append(sub_result)
        
        # Final coordination
        final_result = await workflow.execute_activity(
            coordinate_final_response_activity,
            coordinator_result,
            sub_results,
            activity_services,
            start_to_close_timeout=timedelta(minutes=5),
        )
        
        return final_result
```

## 🔧 Implementation Plan

### **Phase 1: Extend Current Single-Agent Workflow**

1. **Add Child Workflow Support**:
   ```python
   # Add to existing AgentExecutionWorkflow
   async def execute_child_agent(self, child_request: AgentExecutionRequest):
       return await workflow.execute_child_workflow(
           AgentExecutionWorkflow.run,
           child_request,
           id=f"child-{child_request.task_id}",
           task_queue="agent-execution",
       )
   ```

2. **Update ADK Adapter**:
   ```python
   # Add child execution capability to ADK adapter
   async def execute_with_child_agents(self, agent, task_query, child_requests):
       # Execute main agent
       result = await self.execute_agent_with_adk(agent, task_query, ...)
       
       # Parse if child agents needed
       if self.needs_child_agents(result):
           child_results = await self.execute_child_agents(child_requests)
           result = self.combine_results(result, child_results)
       
       return result
   ```

### **Phase 2: Implement Multi-Agent Workflows**

1. **Create Multi-Agent Request Models**:
   ```python
   @dataclass
   class MultiAgentRequest:
       task_id: UUID
       user_id: str
       main_task_query: str
       agent_sequence: List[UUID]  # For sequential execution
       execution_strategy: str  # "sequential", "parallel", "coordinator"
   ```

2. **Implement Coordination Activities**:
   ```python
   @activity.defn
   async def coordinate_multi_agent_execution_activity(
       request: MultiAgentRequest,
       activity_services: ActivityServicesInterface,
   ) -> Dict[str, Any]:
       # Coordination logic
       pass
   ```

### **Phase 3: Advanced Multi-Agent Features**

1. **Agent Communication**:
   - Inter-agent messaging
   - Shared context and memory
   - State synchronization

2. **Dynamic Agent Selection**:
   - Agent capability matching
   - Load balancing
   - Fallback mechanisms

3. **Advanced Coordination**:
   - Hierarchical agent structures
   - Conditional execution paths
   - Result aggregation strategies

## 📊 Testing Execution Strategy

### **Run Complete Test Suite**

```bash
# Install test dependencies
pip install pytest pytest-asyncio pytest-mock

# Run all tests
pytest core/libs/execution/tests/ -v

# Run specific test types
pytest core/libs/execution/tests/ -m "unit" -v          # Unit tests
pytest core/libs/execution/tests/ -m "integration" -v  # Integration tests
pytest core/libs/execution/tests/ -m "e2e" -v          # End-to-end tests

# Run with coverage
pytest core/libs/execution/tests/ --cov=agentarea_execution --cov-report=html
```

### **Testing Checklist**

- [ ] **Unit Tests**: Individual activities work correctly
- [ ] **Integration Tests**: Workflow orchestration works with mocked activities
- [ ] **Multi-Agent Tests**: Child workflow execution works correctly
- [ ] **Timeout Tests**: Proper timeout handling in multi-agent scenarios
- [ ] **Error Recovery**: Child workflow failures don't break parent workflow
- [ ] **Performance Tests**: Multi-agent execution scales appropriately
- [ ] **E2E Tests**: Complete workflow execution with real Temporal server

## 🚀 Next Steps

1. **Implement Basic Child Workflow Support** in current `AgentExecutionWorkflow`
2. **Create Comprehensive Test Suite** following Temporal best practices
3. **Build Multi-Agent Coordination Activities**
4. **Implement Sequential and Parallel Multi-Agent Workflows**
5. **Add Agent Communication Capabilities**
6. **Deploy and Monitor Multi-Agent Execution**

---

**Status**: 🏗️ **Design Complete** - Ready for implementation based on Child Workflows pattern 