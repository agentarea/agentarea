#!/usr/bin/env python3
"""
Test script to verify SSE endpoint works with a simple ADK agent.

This script:
1. Creates a simple ADK agent
2. Starts a Temporal workflow with that agent
3. Tests the SSE endpoint to see if we get real-time events
"""

import asyncio
import logging
import time

import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def create_simple_adk_agent():
    """Create a simple ADK agent configuration for testing."""
    agent_config = {
        "name": "simple_test_agent",
        "model": "ollama_chat/qwen2.5",  # Using local model for testing
        "instructions": "You are a helpful assistant. Answer questions briefly and clearly.",
        "description": "Simple test agent for SSE verification",
        "enable_streaming": True,  # Enable streaming for real-time events
    }
    return agent_config


def test_sse_endpoint(agent_id: str, task_id: str, base_url: str = "http://localhost:8000"):
    """Test the SSE endpoint to see if it's working."""
    print(f"📡 Testing SSE endpoint for task {task_id}")

    # SSE endpoint URL
    sse_url = f"{base_url}/api/v1/agents/{agent_id}/tasks/{task_id}/events/stream"
    print(f"   Endpoint: {sse_url}")

    try:
        # Use requests with streaming to test SSE
        with requests.get(sse_url, stream=True, timeout=30) as response:
            print(f"   Status: {response.status_code}")

            if response.status_code == 200:
                print("   ✅ Connected to SSE stream")
                print("   Listening for events (waiting 10 seconds)...")

                # Read events for 10 seconds
                start_time = time.time()
                event_count = 0

                for line in response.iter_lines():
                    if line:
                        decoded_line = line.decode("utf-8")
                        print(f"   📥 {decoded_line}")
                        event_count += 1

                    # Stop after 10 seconds or 5 events
                    if time.time() - start_time > 10 or event_count >= 5:
                        break

                print(
                    f"   📊 Received {event_count} events in {time.time() - start_time:.1f} seconds"
                )
                return True
            else:
                print(f"   ❌ Failed to connect: {response.status_code}")
                return False

    except Exception as e:
        print(f"   ❌ SSE connection failed: {e}")
        return False


async def create_test_task(agent_id: str, base_url: str = "http://localhost:8000"):
    """Create a test task using the API."""
    print("📝 Creating test task...")

    task_url = f"{base_url}/api/v1/agents/{agent_id}/tasks"

    task_data = {
        "description": "Test task for SSE verification",
        "user_id": "test_user",
        "enable_agent_communication": True,
        "task_parameters": {
            "enable_streaming": True,  # Enable streaming for this task
            "model": "ollama_chat/qwen2.5",
            "instructions": "You are a helpful assistant. Answer questions briefly and clearly.",
        },
    }

    try:
        response = requests.post(task_url, json=task_data)
        print(f"   Status: {response.status_code}")

        if response.status_code == 200:
            task_info = response.json()
            task_id = task_info.get("id")
            print(f"   ✅ Task created: {task_id}")
            return task_id
        else:
            print(f"   ❌ Failed to create task: {response.text}")
            return None

    except Exception as e:
        print(f"   ❌ Task creation failed: {e}")
        return None


def get_test_agent():
    """Get or create a test agent for testing."""
    print("🤖 Getting test agent...")

    base_url = "http://localhost:8000"
    agents_url = f"{base_url}/api/v1/agents"

    try:
        # Try to get existing agents
        response = requests.get(agents_url)
        if response.status_code == 200:
            agents = response.json()
            if agents:
                # Use the first available agent
                agent = agents[0]
                agent_id = agent.get("id")
                print(f"   ✅ Using existing agent: {agent_id} ({agent.get('name', 'unnamed')})")
                return agent_id

        print("   ⚠️  No existing agents found")
        return None

    except Exception as e:
        print(f"   ❌ Failed to get agents: {e}")
        return None


async def trigger_agent_execution(
    agent_id: str, task_id: str, base_url: str = "http://localhost:8000"
):
    """Trigger agent execution to generate events."""
    print("🎯 Triggering agent execution...")

    execute_url = f"{base_url}/api/v1/agents/{agent_id}/tasks/{task_id}/execute"

    execute_data = {
        "query": "Please explain what SSE (Server-Sent Events) is and how it works in simple terms.",
        "enable_streaming": True,
    }

    try:
        response = requests.post(execute_url, json=execute_data)
        print(f"   Status: {response.status_code}")

        if response.status_code == 200:
            print("   ✅ Execution triggered")
            return True
        else:
            print(f"   ❌ Failed to trigger execution: {response.text}")
            return False

    except Exception as e:
        print(f"   ❌ Execution trigger failed: {e}")
        return False


async def main():
    """Main test function."""
    print("🚀 SSE + ADK Agent Test")
    print("=" * 50)

    # Check if API is running
    base_url = "http://localhost:8000"
    try:
        response = requests.get(f"{base_url}/health")
        if response.status_code != 200:
            print("❌ API is not running. Please start the API first:")
            print("   make run-api")
            return
        print("✅ API is running")
    except Exception as e:
        print(f"❌ Cannot connect to API: {e}")
        print("   Please start the API first:")
        print("   make run-api")
        return

    # Get or create test agent
    agent_id = get_test_agent()
    if not agent_id:
        print("⚠️  No agent available. Please create an agent first.")
        return

    # Create test task
    task_id = await create_test_task(agent_id, base_url)
    if not task_id:
        print("❌ Failed to create test task")
        return

    print()

    # Start SSE testing in background
    print("🔄 Starting SSE monitoring...")
    sse_task = asyncio.create_task(
        asyncio.to_thread(test_sse_endpoint, agent_id, task_id, base_url)
    )

    # Give SSE a moment to start
    await asyncio.sleep(1)

    # Trigger agent execution
    await trigger_agent_execution(agent_id, task_id, base_url)

    # Wait for SSE to complete
    await sse_task

    if True:  # Always show results
        print("\n🎉 SSE Test Results:")
        print("   ✅ Test completed")
        print("   ✅ Check the logs above for SSE events")


if __name__ == "__main__":
    asyncio.run(main())
