#!/usr/bin/env python3
"""Simple test to verify SSE implementation works."""

import asyncio
import json
import logging
from datetime import UTC, datetime
from uuid import uuid4

from agentarea_api.api.v1.agents_tasks import _format_sse_event

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def test_sse_formatting():
    """Test SSE event formatting function."""
    logger.info("=== Testing SSE Event Formatting ===")
    
    # Test data
    test_events = [
        {
            "event_type": "connected",
            "data": {
                "task_id": str(uuid4()),
                "agent_id": str(uuid4()),
                "message": "Connected to task event stream"
            }
        },
        {
            "event_type": "WorkflowStarted", 
            "data": {
                "task_id": str(uuid4()),
                "agent_id": str(uuid4()),
                "execution_id": "agent-task-123",
                "timestamp": datetime.now(UTC).isoformat()
            }
        },
        {
            "event_type": "WorkflowLLMCallStarted",
            "data": {
                "task_id": str(uuid4()),
                "model": "gpt-4",
                "estimated_cost": 0.01,
                "prompt_tokens": 100
            }
        },
        {
            "event_type": "heartbeat",
            "data": {
                "timestamp": datetime.now(UTC).isoformat()
            }
        }
    ]
    
    logger.info("Testing SSE formatting for different event types:")
    
    for i, event in enumerate(test_events, 1):
        try:
            formatted = _format_sse_event(event["event_type"], event["data"])
            
            # Verify format
            assert "event: " in formatted
            assert "data: " in formatted 
            assert formatted.endswith("\n\n")
            
            # Verify data is valid JSON
            data_line = [line for line in formatted.split('\n') if line.startswith('data: ')][0]
            data_json = data_line.split('data: ', 1)[1]
            parsed = json.loads(data_json)
            
            logger.info(f"✅ Event {i} ({event['event_type']}): OK")
            logger.info(f"   Formatted: {repr(formatted[:100])}...")
            
        except Exception as e:
            logger.error(f"❌ Event {i} ({event['event_type']}): {e}")
            return False
    
    logger.info("✅ All SSE formatting tests passed!")
    return True


async def test_task_service_streaming():
    """Test TaskService streaming interface (mock version)."""
    logger.info("=== Testing TaskService Streaming Interface ===")
    
    # Import the TaskService and create minimal setup
    try:
        from agentarea_tasks.task_service import TaskService
        
        # Mock dependencies
        class MockTaskRepository:
            async def get(self, task_id): 
                from agentarea_tasks.domain.models import SimpleTask
                return SimpleTask(
                    id=task_id,
                    title="Test",
                    description="Test",
                    query="Test",
                    user_id="test",
                    agent_id=uuid4(),
                    status="running"
                )
            
            async def create(self, task): return task
            async def update(self, task): return task
        
        class MockEventBroker:
            async def publish(self, event): pass
        
        class MockTaskManager:
            async def submit_task(self, task): return task
            async def cancel_task(self, task_id): return True
        
        # Create service
        service = TaskService(
            task_repository=MockTaskRepository(),
            event_broker=MockEventBroker(),
            task_manager=MockTaskManager()
        )
        
        task_id = uuid4()
        logger.info(f"Testing stream for task: {task_id}")
        
        # Test streaming (should yield historical events and then timeout with heartbeat)
        events_received = []
        
        try:
            async for event in service.stream_task_events(task_id, include_history=True):
                events_received.append(event)
                logger.info(f"Received event: {event['event_type']}")
                
                # Stop after a few events to avoid infinite loop
                if len(events_received) >= 2:
                    break
        
        except Exception as e:
            logger.info(f"Stream ended (expected): {e}")
        
        # Should have received at least historical events
        if len(events_received) > 0:
            logger.info(f"✅ Received {len(events_received)} events from TaskService")
            return True
        else:
            logger.warning("⚠️  No events received - this may be expected in test environment")
            return False
            
    except Exception as e:
        logger.error(f"❌ TaskService streaming test failed: {e}")
        return False


def test_workflow_integration():
    """Test that workflow event types are properly defined."""
    logger.info("=== Testing Workflow Event Integration ===")
    
    try:
        from agentarea_api.api.events.event_types import EventType
        
        expected_events = [
            EventType.WORKFLOW_STARTED,
            EventType.WORKFLOW_LLM_CALL_STARTED, 
            EventType.WORKFLOW_BUDGET_WARNING,
            EventType.WORKFLOW_COMPLETED
        ]
        
        logger.info("Checking workflow event types:")
        for event_type in expected_events:
            logger.info(f"  ✅ {event_type.value}")
        
        logger.info("✅ All workflow event types are properly defined!")
        return True
        
    except ImportError as e:
        logger.error(f"❌ Event types not properly imported: {e}")
        return False


async def run_simple_tests():
    """Run all simple tests."""
    logger.info("🚀 Running Simple SSE Tests")
    logger.info("=" * 50)
    
    results = {
        "sse_formatting": test_sse_formatting(),
        "workflow_events": test_workflow_integration(), 
        "task_streaming": await test_task_service_streaming(),
    }
    
    # Summary
    logger.info("=" * 50)
    logger.info("🏁 Simple Test Results:")
    
    passed = sum(results.values())
    total = len(results)
    
    for test_name, passed_test in results.items():
        status = "✅ PASSED" if passed_test else "❌ FAILED"
        logger.info(f"  {test_name}: {status}")
    
    logger.info(f"Total: {passed}/{total} tests passed")
    
    if passed == total:
        logger.info("🎉 All simple tests passed!")
        logger.info("💡 The SSE streaming implementation is working correctly!")
    else:
        logger.info("⚠️  Some tests failed - check implementation")
    
    return results


if __name__ == "__main__":
    asyncio.run(run_simple_tests())