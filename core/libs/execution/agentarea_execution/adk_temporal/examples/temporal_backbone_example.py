"""Example demonstrating Temporal backbone integration with ADK agents.

This example shows how ADK agents can use Temporal as the execution backbone
for tool and LLM calls while keeping the ADK library mostly untouched.
"""

import asyncio
import logging
from typing import Dict, Any
from uuid import uuid4

from temporalio import workflow
from temporalio.client import Client
from temporalio.worker import Worker

from ..services.adk_service_factory import create_adk_runner
from ..utils.agent_builder import create_simple_agent_config
from ..activities.adk_agent_activities import execute_agent_step

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@workflow.defn
class TemporalBackboneAgentWorkflow:
    """Workflow demonstrating Temporal backbone integration."""
    
    def __init__(self):
        self.events = []
        self.agent_config = {}
        self.session_data = {}
    
    @workflow.run
    async def run(self, agent_config: Dict[str, Any], session_data: Dict[str, Any], user_message: str) -> Dict[str, Any]:
        """Run agent with Temporal backbone.
        
        Args:
            agent_config: Agent configuration
            session_data: Session data
            user_message: User message to process
            
        Returns:
            Execution result with events
        """
        self.agent_config = agent_config
        self.session_data = session_data
        
        logger.info(f"Starting Temporal backbone workflow for agent: {agent_config.get('name', 'unknown')}")
        
        try:
            # Prepare user message
            message_dict = {
                "content": user_message,
                "role": "user"
            }
            
            # Execute agent step with Temporal backbone
            # This will route tool and LLM calls through Temporal activities
            events = await workflow.execute_activity(
                execute_agent_step,
                args=[agent_config, session_data, message_dict],
                start_to_close_timeout=600,  # 10 minutes
                heartbeat_timeout=30,  # 30 seconds
            )
            
            self.events.extend(events)
            
            # Extract final response
            final_response = None
            for event in reversed(events):
                if event.get("is_final_response", False):
                    final_response = event.get("content", {}).get("text", "No response")
                    break
            
            if not final_response:
                # Look for assistant response in events
                for event in reversed(events):
                    if event.get("author") == agent_config.get("name", "agent"):
                        content = event.get("content", {})
                        if isinstance(content, dict) and "parts" in content:
                            for part in content["parts"]:
                                if part.get("text"):
                                    final_response = part["text"]
                                    break
                        if final_response:
                            break
            
            result = {
                "success": True,
                "final_response": final_response or "Agent completed execution",
                "event_count": len(events),
                "events": events[:5],  # Return first 5 events for brevity
            }
            
            logger.info(f"Temporal backbone workflow completed successfully with {len(events)} events")
            return result
            
        except Exception as e:
            logger.error(f"Temporal backbone workflow failed: {e}")
            return {
                "success": False,
                "error": str(e),
                "event_count": len(self.events),
                "events": self.events
            }
    
    @workflow.query
    def get_events(self) -> list:
        """Get current events."""
        return self.events
    
    @workflow.query
    def get_status(self) -> Dict[str, Any]:
        """Get current workflow status."""
        return {
            "event_count": len(self.events),
            "agent_name": self.agent_config.get("name", "unknown"),
            "session_id": self.session_data.get("session_id", "unknown")
        }


async def run_temporal_backbone_example():
    """Run the Temporal backbone integration example."""
    logger.info("Starting Temporal backbone integration example")
    
    try:
        # Connect to Temporal server
        client = await Client.connect("localhost:7233")
        
        # Create agent configuration
        agent_config = create_simple_agent_config(
            name="temporal_enhanced_agent",
            model="gpt-4",
            instructions="You are a helpful assistant that can use tools and answer questions.",
            description="An agent enhanced with Temporal backbone for tool and LLM execution",
            tools=[
                {
                    "name": "calculator",
                    "description": "Perform mathematical calculations",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "expression": {
                                "type": "string",
                                "description": "Mathematical expression to evaluate"
                            }
                        },
                        "required": ["expression"]
                    }
                }
            ]
        )
        
        # Create session data
        session_data = {
            "user_id": "example_user",
            "session_id": f"session_{uuid4()}",
            "app_name": "temporal_backbone_example"
        }
        
        # Start workflow
        workflow_id = f"temporal-backbone-{uuid4()}"
        handle = await client.start_workflow(
            TemporalBackboneAgentWorkflow.run,
            args=[agent_config, session_data, "Hello! Can you calculate 15 * 23 for me?"],
            id=workflow_id,
            task_queue="agent-execution"
        )
        
        logger.info(f"Started workflow: {workflow_id}")
        
        # Wait for result
        result = await handle.result()
        
        logger.info("Temporal backbone example completed!")
        logger.info(f"Success: {result['success']}")
        logger.info(f"Final response: {result.get('final_response', 'No response')}")
        logger.info(f"Event count: {result['event_count']}")
        
        return result
        
    except Exception as e:
        logger.error(f"Temporal backbone example failed: {e}")
        raise


async def run_worker():
    """Run Temporal worker for the example."""
    logger.info("Starting Temporal worker for backbone example")
    
    try:
        # Connect to Temporal server
        client = await Client.connect("localhost:7233")
        
        # Import activities
        from ..activities.agent_execution_activities import make_agent_activities
        from ...interfaces import ActivityDependencies
        
        # Create mock dependencies for example
        class MockEventBroker:
            async def publish(self, event):
                logger.info(f"Mock event published: {event}")
        
        class MockSecretManager:
            async def get_secret(self, key):
                return f"mock_secret_for_{key}"
        
        dependencies = ActivityDependencies(
            event_broker=MockEventBroker(),
            secret_manager=MockSecretManager()
        )
        
        # Create activities
        activities = make_agent_activities(dependencies)
        activities.append(execute_agent_step)
        
        # Create and run worker
        worker = Worker(
            client,
            task_queue="agent-execution",
            workflows=[TemporalBackboneAgentWorkflow],
            activities=activities,
        )
        
        logger.info("Worker started, waiting for tasks...")
        await worker.run()
        
    except Exception as e:
        logger.error(f"Worker failed: {e}")
        raise


async def main():
    """Main function to demonstrate the integration."""
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "worker":
        # Run worker
        await run_worker()
    else:
        # Run example
        await run_temporal_backbone_example()


if __name__ == "__main__":
    asyncio.run(main())