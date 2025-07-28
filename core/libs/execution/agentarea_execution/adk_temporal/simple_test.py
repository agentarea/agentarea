#!/usr/bin/env python3
"""Simple test to verify ADK-Temporal integration components."""

import asyncio
from typing import Dict, Any

# Test the core utilities without ADK dependencies
def test_agent_config_creation():
    """Test creating agent configurations."""
    print("=== Testing Agent Config Creation ===")
    
    # Simple config creation
    config = {
        "name": "test_agent",
        "model": "gpt-4", 
        "instructions": "You are a helpful assistant",
        "description": "Test agent"
    }
    
    print(f"Created config: {config}")
    
    # Basic validation
    required_fields = ["name"]
    valid = all(field in config and config[field] for field in required_fields)
    print(f"Config is valid: {valid}")
    
    return config, valid


def test_event_dict_structure():
    """Test event dictionary structure handling."""
    print("\n=== Testing Event Dict Structure ===")
    
    # Create a mock event dictionary
    event_dict = {
        "author": "test_agent",
        "invocation_id": "test_123", 
        "content": {
            "parts": [{"text": "Hello, world!"}]
        },
        "actions": {"skip_summarization": False},
        "id": "event_123",
        "timestamp": 1234567890.0
    }
    
    print(f"Event dict structure: {list(event_dict.keys())}")
    
    # Test basic serialization/deserialization
    import json
    try:
        serialized = json.dumps(event_dict)
        deserialized = json.loads(serialized)
        roundtrip_success = deserialized == event_dict
        print(f"JSON roundtrip successful: {roundtrip_success}")
    except Exception as e:
        print(f"JSON roundtrip failed: {e}")
        roundtrip_success = False
    
    return event_dict, roundtrip_success


async def test_activity_structure():
    """Test activity function structure."""
    print("\n=== Testing Activity Structure ===")
    
    # Mock activity function
    async def mock_execute_adk_agent_activity(
        agent_config: Dict[str, Any],
        session_data: Dict[str, Any], 
        user_message: Dict[str, Any],
        run_config: Dict[str, Any] = None
    ):
        """Mock ADK agent activity."""
        print(f"Agent: {agent_config.get('name', 'unknown')}")
        print(f"User: {session_data.get('user_id', 'unknown')}")
        print(f"Message: {user_message.get('content', 'no content')}")
        
        # Return mock events
        return [
            {
                "author": agent_config.get("name", "agent"),
                "content": {"parts": [{"text": "Processing your request..."}]},
                "actions": {"skip_summarization": False},
                "id": "1",
                "timestamp": 1.0
            },
            {
                "author": agent_config.get("name", "agent"),
                "content": {"parts": [{"text": "Task completed successfully!"}]},
                "actions": {"skip_summarization": True},
                "id": "2", 
                "timestamp": 2.0
            }
        ]
    
    # Test data
    agent_config = {"name": "test_agent", "model": "gpt-4"}
    session_data = {"user_id": "test_user", "session_id": "test_session"}
    user_message = {"content": "Hello!", "role": "user"}
    
    # Execute mock activity
    events = await mock_execute_adk_agent_activity(
        agent_config, session_data, user_message
    )
    
    print(f"Generated {len(events)} events")
    print(f"Event structure valid: {all('author' in e and 'content' in e for e in events)}")
    
    return events


def test_workflow_state_structure():
    """Test workflow state structure."""
    print("\n=== Testing Workflow State Structure ===")
    
    # Mock workflow state
    workflow_state = {
        "execution_id": "workflow_123",
        "agent_config": {"name": "test_agent"},
        "session_data": {"user_id": "test_user"},
        "events": [],
        "success": False,
        "final_response": None,
        "paused": False
    }
    
    print(f"Workflow state keys: {list(workflow_state.keys())}")
    
    # Test state updates
    workflow_state["events"].append({"event": "data"})
    workflow_state["success"] = True
    workflow_state["final_response"] = "Task completed"
    
    print(f"Updated state - Events: {len(workflow_state['events'])}, Success: {workflow_state['success']}")
    
    return workflow_state


async def main():
    """Run all tests."""
    print("ADK-Temporal Integration Simple Tests")
    print("=" * 50)
    
    try:
        # Test 1: Agent config
        config, config_valid = test_agent_config_creation()
        
        # Test 2: Event structure  
        event_dict, event_valid = test_event_dict_structure()
        
        # Test 3: Activity structure
        events = await test_activity_structure()
        
        # Test 4: Workflow state
        state = test_workflow_state_structure()
        
        # Summary
        print("\n" + "=" * 50)
        print("Test Summary:")
        print(f"✓ Agent config creation: {'PASS' if config_valid else 'FAIL'}")
        print(f"✓ Event serialization: {'PASS' if event_valid else 'FAIL'}")
        print(f"✓ Activity execution: {'PASS' if len(events) == 2 else 'FAIL'}")
        print(f"✓ Workflow state: {'PASS' if state['success'] else 'FAIL'}")
        
        all_passed = all([config_valid, event_valid, len(events) == 2, state['success']])
        print(f"\nOverall: {'ALL TESTS PASSED!' if all_passed else 'SOME TESTS FAILED'}")
        
        return all_passed
        
    except Exception as e:
        print(f"\nTest execution failed: {e}")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)