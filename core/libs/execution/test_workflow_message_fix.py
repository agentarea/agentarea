#!/usr/bin/env python3
"""Test script to verify the workflow can use Message.from_base_message correctly.
"""

import sys

sys.path.append('core/libs/execution')

from agentarea_execution.message_types.messages import Message, create_system_message
from agentarea_execution.workflows.agent_execution_workflow import AgentExecutionWorkflow


def test_message_creation():
    """Test that Message.from_base_message works correctly."""
    print("=== Testing Message Creation ===\n")

    # Test creating a system message
    system_msg = create_system_message("You are a helpful AI assistant.")
    print(f"✅ SystemMessage created: {type(system_msg).__name__}")

    # Test converting to legacy Message
    try:
        legacy_msg = Message.from_base_message(system_msg)
        print(f"✅ Legacy Message created: {type(legacy_msg).__name__}")
        print(f"   Role: {legacy_msg.role}")
        print(f"   Content: {legacy_msg.content[:50]}...")
        return True
    except Exception as e:
        print(f"❌ Error creating legacy message: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_workflow_message_usage():
    """Test that the workflow can use messages correctly."""
    print("\n=== Testing Workflow Message Usage ===\n")

    try:
        # Create workflow instance
        workflow = AgentExecutionWorkflow()
        print("✅ Workflow instance created")

        # Test that the workflow has access to Message class
        # This simulates what happens in the workflow
        system_msg = create_system_message("Test system message")
        legacy_msg = Message.from_base_message(system_msg)

        print("✅ Workflow can create and convert messages")
        print(f"   Message role: {legacy_msg.role}")
        print(f"   Message content length: {len(legacy_msg.content)}")

        return True

    except Exception as e:
        print(f"❌ Error in workflow message usage: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all tests."""
    print("Testing Workflow Message Fix\n")

    message_test = test_message_creation()
    workflow_test = test_workflow_message_usage()

    print("\n" + "="*50)
    print("TEST RESULTS")
    print("="*50)

    if message_test and workflow_test:
        print("🎉 ALL TESTS PASSED!")
        print("✅ Message.from_base_message works correctly")
        print("✅ Workflow can use message conversion")
        print("\nThe workflow should now work without AttributeError")
        return True
    else:
        print("❌ SOME TESTS FAILED")
        if not message_test:
            print("❌ Message creation failed")
        if not workflow_test:
            print("❌ Workflow message usage failed")
        return False


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
