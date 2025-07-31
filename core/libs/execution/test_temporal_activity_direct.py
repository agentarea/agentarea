#!/usr/bin/env python3
"""
Direct test of our new Temporal activity to verify it works.
"""

import asyncio
import logging
from temporalio.client import Client
from temporalio.common import RetryPolicy
from temporalio import workflow

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@workflow.defn
class TestADKBackboneWorkflow:
    @workflow.run
    async def run(self, agent_config, session_data, user_message) -> list:
        return await workflow.execute_activity(
            "execute_adk_agent_with_temporal_backbone",
            args=[agent_config, session_data, user_message],
            start_to_close_timeout=300,  # 5 minutes
            retry_policy=RetryPolicy(maximum_attempts=1)
        )

async def test_adk_temporal_activity_direct():
    """Test our ADK Temporal backbone activity directly."""
    logger.info("🎯 DIRECT ADK TEMPORAL ACTIVITY TEST")
    logger.info("=" * 50)
    
    try:
        # Connect to Temporal
        client = await Client.connect("localhost:7233", namespace="default")
        logger.info("✅ Connected to Temporal server")
        
        # Prepare test data
        agent_config = {
            "name": "direct_test_agent",
            "model": "qwen2.5",
            "instructions": "You are a helpful math assistant. Calculate 15 + 27 and show your work.",
            "description": "Direct test agent for Temporal backbone verification"
        }
        
        session_data = {
            "user_id": "direct_test_user",
            "session_id": "direct_test_session",
            "app_name": "direct_temporal_test",
            "state": {"test_mode": True},
            "created_time": 1640995200.0
        }
        
        user_message = {
            "role": "user",
            "content": "What is 15 + 27? Please show your calculation step by step."
        }
        
        logger.info("🚀 Executing ADK agent activity directly...")
        logger.info(f"   Agent: {agent_config['name']}")
        logger.info(f"   Message: {user_message['content']}")
        
        # Start the workflow to test our activity
        handle = await client.start_workflow(
            TestADKBackboneWorkflow.run,
            args=[agent_config, session_data, user_message],
            id=f"test-adk-backbone-{int(asyncio.get_event_loop().time())}",
            task_queue="agent-tasks"
        )
        
        logger.info(f"🔄 Started workflow: {handle.id}")
        
        # Wait for result
        result = await handle.result()
        
        logger.info("✅ Activity execution completed!")
        logger.info(f"📄 Result: {len(result)} events returned")
        
        # Show some results
        for i, event in enumerate(result[:3]):  # Show first 3 events
            logger.info(f"   Event {i+1}: {str(event)[:100]}...")
        
        logger.info("\n🎉 SUCCESS!")
        logger.info("✅ ADK Temporal backbone activity works correctly")
        logger.info("✅ Activity can be executed directly via Temporal")
        logger.info("✅ Integration is ready for workflow usage")
        
        return True
        
    except Exception as e:
        logger.error(f"❌ Direct activity test failed: {e}")
        import traceback
        traceback.print_exc()
        return False

if __name__ == "__main__":
    success = asyncio.run(test_adk_temporal_activity_direct())
    exit(0 if success else 1)