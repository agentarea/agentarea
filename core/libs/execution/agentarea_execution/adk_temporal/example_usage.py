"""Example usage of ADK-Temporal integration.

This demonstrates how to use the ADK-Temporal integration to run
Google ADK agents through Temporal workflows.
"""

import asyncio
from uuid import uuid4
from temporalio.client import Client
from temporalio.worker import Worker

from .workflows.adk_agent_workflow import ADKAgentWorkflow
from .activities.adk_agent_activities import (
    execute_adk_agent_activity,
    validate_adk_agent_config,
    stream_adk_agent_activity
)
from .utils.agent_builder import create_simple_agent_config
from .services.adk_service_factory import create_default_session_data
from ..models import AgentExecutionRequest


async def example_simple_agent_execution():
    """Example of executing a simple ADK agent through Temporal."""
    print("=== Simple ADK Agent Execution Example ===")
    
    # Create agent configuration
    agent_config = create_simple_agent_config(
        name="math_assistant",
        model="gpt-4",
        instructions="You are a helpful math assistant. Solve problems step by step.",
        description="Math problem solving agent"
    )
    
    # Create session data
    session_data = create_default_session_data(
        user_id="example_user",
        app_name="adk_temporal_example"
    )
    
    # Create user message
    user_message = {
        "content": "What is 15 * 23? Please show your work.",
        "role": "user"
    }
    
    # Execute the agent directly through the activity
    print("Executing ADK agent...")
    try:
        events = await execute_adk_agent_activity(
            agent_config,
            session_data,
            user_message
        )
        
        print(f"Agent execution completed with {len(events)} events:")
        for i, event in enumerate(events):
            print(f"  Event {i+1}: {event.get('content', {}).get('parts', [{}])[0].get('text', 'No text')[:100]}...")
        
        return events
        
    except Exception as e:
        print(f"Agent execution failed: {e}")
        return []


async def example_workflow_execution():
    """Example of executing ADK agent through Temporal workflow."""
    print("\n=== ADK Agent Workflow Execution Example ===")
    
    try:
        # Connect to Temporal server (assumes local Temporal server running)
        client = await Client.connect("localhost:7233")
        
        # Create execution request
        request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            task_query="Explain the concept of recursion in programming with a simple example.",
            task_parameters={
                "detail_level": "beginner",
                "include_code": True
            },
            requires_human_approval=False,
            budget_usd=5.0
        )
        
        # Start the workflow
        print("Starting ADK agent workflow...")
        workflow_handle = await client.start_workflow(
            ADKAgentWorkflow.run,
            request,
            id=f"adk-agent-{request.task_id}",
            task_queue="adk-agent-queue"
        )
        
        print(f"Workflow started with ID: {workflow_handle.id}")
        
        # Query workflow state periodically
        for i in range(5):
            await asyncio.sleep(2)
            try:
                state = await workflow_handle.query(ADKAgentWorkflow.get_current_state)
                print(f"Workflow state: {state['event_count']} events, success: {state['success']}")
                
                if state['has_final_response']:
                    final_response = await workflow_handle.query(ADKAgentWorkflow.get_final_response)
                    print(f"Final response preview: {final_response[:100]}...")
                    break
            except Exception as e:
                print(f"Query failed: {e}")
        
        # Wait for workflow completion
        print("Waiting for workflow completion...")
        result = await workflow_handle.result()
        
        print(f"Workflow completed successfully: {result.success}")
        print(f"Final response: {result.final_response[:200]}...")
        print(f"Total iterations: {result.reasoning_iterations_used}")
        print(f"Total cost: ${result.total_cost:.4f}")
        
        return result
        
    except Exception as e:
        print(f"Workflow execution failed: {e}")
        return None


async def example_agent_validation():
    """Example of validating agent configurations."""
    print("\n=== Agent Configuration Validation Example ===")
    
    # Valid configuration
    valid_config = create_simple_agent_config(
        name="validation_test_agent",
        model="gpt-4",
        instructions="You are a test agent for validation."
    )
    
    print("Validating valid configuration...")
    result = await validate_adk_agent_config(valid_config)
    print(f"Valid: {result['valid']}")
    print(f"Errors: {result['errors']}")
    print(f"Warnings: {result['warnings']}")
    
    # Invalid configuration
    invalid_config = {
        "model": "gpt-4",
        "tools": "not_a_list"  # Should be a list
        # Missing required 'name' field
    }
    
    print("\nValidating invalid configuration...")
    result = await validate_adk_agent_config(invalid_config)
    print(f"Valid: {result['valid']}")
    print(f"Errors: {result['errors']}")
    print(f"Warnings: {result['warnings']}")


async def example_workflow_control():
    """Example of workflow pause/resume control."""
    print("\n=== Workflow Control Example ===")
    
    try:
        # This would require a running Temporal worker
        client = await Client.connect("localhost:7233")
        
        # Create a long-running task
        request = AgentExecutionRequest(
            task_id=uuid4(),
            agent_id=uuid4(),
            task_query="Write a detailed essay about the history of artificial intelligence, covering major milestones from the 1950s to today.",
            task_parameters={},
            requires_human_approval=False,
            budget_usd=20.0
        )
        
        # Start workflow
        workflow_handle = await client.start_workflow(
            ADKAgentWorkflow.run,
            request,
            id=f"adk-control-{request.task_id}",
            task_queue="adk-agent-queue"
        )
        
        print(f"Started workflow: {workflow_handle.id}")
        
        # Let it run for a bit
        await asyncio.sleep(5)
        
        # Pause the workflow
        print("Pausing workflow...")
        await workflow_handle.signal(ADKAgentWorkflow.pause, "Manual pause for demonstration")
        
        # Check state
        state = await workflow_handle.query(ADKAgentWorkflow.get_current_state)
        print(f"Workflow paused: {state['paused']}, reason: {state['pause_reason']}")
        
        # Wait a bit
        await asyncio.sleep(3)
        
        # Resume the workflow
        print("Resuming workflow...")
        await workflow_handle.signal(ADKAgentWorkflow.resume, "Manual resume")
        
        # Check state again
        state = await workflow_handle.query(ADKAgentWorkflow.get_current_state)
        print(f"Workflow paused: {state['paused']}")
        
        print("Workflow control demonstration complete")
        
    except Exception as e:
        print(f"Workflow control example failed: {e}")


async def run_worker():
    """Run a Temporal worker for the examples."""
    print("\n=== Starting Temporal Worker ===")
    
    try:
        # Connect to Temporal
        client = await Client.connect("localhost:7233")
        
        # Create worker
        worker = Worker(
            client,
            task_queue="adk-agent-queue",
            workflows=[ADKAgentWorkflow],
            activities=[
                execute_adk_agent_activity,
                validate_adk_agent_config,
                stream_adk_agent_activity
            ]
        )
        
        print("Worker started. Press Ctrl+C to stop.")
        await worker.run()
        
    except KeyboardInterrupt:
        print("Worker stopped by user")
    except Exception as e:
        print(f"Worker failed: {e}")


async def main():
    """Main example function."""
    print("ADK-Temporal Integration Examples")
    print("=" * 40)
    
    # Run examples that don't require Temporal server
    await example_agent_validation()
    await example_simple_agent_execution()
    
    print("\n" + "=" * 40)
    print("The following examples require a running Temporal server:")
    print("1. Start Temporal server: temporal server start-dev")
    print("2. Run this script with worker: python -c 'from adk_temporal.example_usage import run_worker; import asyncio; asyncio.run(run_worker())'")
    print("3. In another terminal, run workflow examples")
    
    # Uncomment these if you have Temporal server running
    # await example_workflow_execution()
    # await example_workflow_control()


if __name__ == "__main__":
    # For direct execution
    asyncio.run(main())