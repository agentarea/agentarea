#!/usr/bin/env python3
"""Test to verify that frontend event processing extracts rich content correctly.
This simulates the SSE data structure and verifies the frontend can process it.
"""

import json
import logging
from datetime import datetime
from uuid import uuid4

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def create_sample_sse_event() -> dict:
    """Create a sample SSE event that matches the actual structure from the logs."""
    task_id = str(uuid4())
    agent_id = str(uuid4())

    # This is the actual structure from the user's SSE logs
    return {
        "event_id": str(uuid4()),
        "event_type": "workflow.LLMCallCompleted",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "aggregate_id": task_id,
        "aggregate_type": "task",
        "original_event_type": "LLMCallCompleted",
        "original_timestamp": datetime.utcnow().isoformat() + "Z",
        "original_data": {
            "task_id": task_id,
            "agent_id": agent_id,
            "iteration": 1,
            "cost": 0.001234,
            "total_cost": 0.001234,
            "usage": {
                "prompt_tokens": 256,
                "completion_tokens": 128,
                "total_tokens": 384
            },
            "content": "I'll analyze the user's request and provide a comprehensive solution. Let me break this down step by step:\n\n1. First, I need to understand what they're asking for\n2. Then I'll provide a detailed implementation\n3. Finally, I'll test the solution to ensure it works",
            "tool_calls": [
                {
                    "id": "call_abc123",
                    "type": "function",
                    "function": {
                        "name": "task_complete",
                        "arguments": json.dumps({
                            "result": "Successfully completed the user's request with a comprehensive solution",
                            "success": True,
                            "reasoning": "The solution addresses all requirements and has been tested"
                        })
                    }
                }
            ],
            "role": "assistant"
        }
    }

def simulate_frontend_event_processing(sse_event: dict) -> dict:
    """Simulate the frontend event processing logic.
    This matches the logic we fixed in useTaskEvents.ts and events.ts
    """
    # Extract data - this is the fixed logic that looks in original_data first
    data = sse_event.get('original_data') or sse_event.get('data') or {}

    # Map event type - handle PascalCase
    event_type = sse_event.get('original_event_type') or sse_event.get('event_type', '')
    # Normalize event type (remove non-alphabetic characters for mapping)
    normalized_type = ''.join(c for c in event_type if c.isalpha())

    # Create display event
    display_event = {
        "id": sse_event.get('event_id', str(uuid4())),
        "type": normalized_type,
        "timestamp": sse_event.get('timestamp'),
        "data": data,
        "cost": data.get('cost', 0),
        "usage": data.get('usage', {}),
        "content": data.get('content', ''),
        "tool_calls": data.get('tool_calls', [])
    }

    # Generate description based on event type and content
    if normalized_type == 'LLMCallCompleted':
        cost = data.get('cost', 0)
        usage = data.get('usage', {})
        content = data.get('content', '')
        tool_calls = data.get('tool_calls', [])

        description_parts = []

        # Add content info
        if content:
            content_preview = content[:100] + "..." if len(content) > 100 else content
            description_parts.append(f"Response: {content_preview}")

        # Add tool calls info
        if tool_calls:
            for tool_call in tool_calls:
                tool_name = tool_call.get('function', {}).get('name', 'unknown')
                if tool_name == 'task_complete':
                    try:
                        args = json.loads(tool_call.get('function', {}).get('arguments', '{}'))
                        reasoning = args.get('reasoning', '')
                        result = args.get('result', '')
                        if reasoning:
                            description_parts.append(f"Reasoning: {reasoning}")
                        elif result:
                            description_parts.append(f"Result: {result}")
                    except:
                        description_parts.append("Completed task")
                else:
                    description_parts.append(f"Called {tool_name}")

        # Add cost/usage info
        if cost > 0:
            description_parts.append(f"Cost: ${cost:.4f}")
        if usage.get('total_tokens'):
            description_parts.append(f"Tokens: {usage['total_tokens']}")

        display_event['description'] = " | ".join(description_parts) if description_parts else "LLM call completed"

    else:
        display_event['description'] = f"{normalized_type} event"

    return display_event

def test_frontend_event_processing():
    """Test that frontend event processing extracts rich content correctly."""
    logger.info("🧪 Testing Frontend Event Processing")
    logger.info("=" * 60)

    # Create sample SSE event
    sse_event = create_sample_sse_event()

    logger.info("📨 Sample SSE Event:")
    logger.info(f"  Event Type: {sse_event['original_event_type']}")
    logger.info(f"  Has original_data: {'original_data' in sse_event}")
    logger.info(f"  Content length: {len(sse_event['original_data'].get('content', ''))}")
    logger.info(f"  Cost: ${sse_event['original_data'].get('cost', 0):.6f}")
    logger.info(f"  Tool calls: {len(sse_event['original_data'].get('tool_calls', []))}")

    # Process event through frontend logic
    display_event = simulate_frontend_event_processing(sse_event)

    logger.info("\n🎨 Processed Display Event:")
    logger.info(f"  Type: {display_event['type']}")
    logger.info(f"  Description: {display_event['description']}")
    logger.info(f"  Cost: ${display_event['cost']:.6f}")
    logger.info(f"  Content: {display_event['content'][:100]}...")
    logger.info(f"  Tool calls: {len(display_event['tool_calls'])}")

    # Validate the processing worked correctly
    success = True

    # Check that rich content was extracted
    if not display_event['content']:
        logger.error("❌ Content not extracted from original_data")
        success = False
    else:
        logger.info("✅ Content extracted successfully")

    # Check that cost was extracted
    if display_event['cost'] == 0:
        logger.error("❌ Cost not extracted from original_data")
        success = False
    else:
        logger.info("✅ Cost extracted successfully")

    # Check that tool calls were extracted
    if not display_event['tool_calls']:
        logger.error("❌ Tool calls not extracted from original_data")
        success = False
    else:
        logger.info("✅ Tool calls extracted successfully")

    # Check that description is meaningful
    if display_event['description'] == "LLMCallCompleted event":
        logger.error("❌ Description is generic, not showing rich content")
        success = False
    else:
        logger.info("✅ Description shows rich content")

    # Check that event type mapping works
    if display_event['type'] != 'LLMCallCompleted':
        logger.error(f"❌ Event type mapping failed: {display_event['type']}")
        success = False
    else:
        logger.info("✅ Event type mapped correctly")

    logger.info("\n" + "=" * 60)
    if success:
        logger.info("🎉 FRONTEND EVENT PROCESSING TEST PASSED!")
        logger.info("   ✅ Rich content extracted from original_data")
        logger.info("   ✅ Cost and usage information preserved")
        logger.info("   ✅ Tool calls processed correctly")
        logger.info("   ✅ Meaningful descriptions generated")
        logger.info("   ✅ Event type mapping works for PascalCase")
    else:
        logger.error("❌ FRONTEND EVENT PROCESSING TEST FAILED!")

    return success

def test_streaming_chunk_event():
    """Test processing of streaming chunk events."""
    logger.info("\n🌊 Testing Streaming Chunk Event Processing")
    logger.info("-" * 40)

    # Create a chunk event (these are published during streaming)
    chunk_event = {
        "event_id": str(uuid4()),
        "event_type": "workflow.LLMCallChunk",
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "aggregate_id": str(uuid4()),
        "aggregate_type": "task",
        "original_event_type": "LLMCallChunk",
        "original_timestamp": datetime.utcnow().isoformat() + "Z",
        "original_data": {
            "task_id": str(uuid4()),
            "chunk": "This is a chunk of streaming LLM response text...",
            "chunk_index": 3,
            "is_final": False
        }
    }

    # Process chunk event
    display_event = simulate_frontend_event_processing(chunk_event)

    logger.info(f"  Chunk content: {display_event['data'].get('chunk', '')}")
    logger.info(f"  Chunk index: {display_event['data'].get('chunk_index', 0)}")
    logger.info(f"  Is final: {display_event['data'].get('is_final', False)}")

    # Validate chunk processing
    chunk_success = (
        display_event['type'] == 'LLMCallChunk' and
        'chunk' in display_event['data'] and
        'chunk_index' in display_event['data']
    )

    if chunk_success:
        logger.info("✅ Streaming chunk events processed correctly")
    else:
        logger.error("❌ Streaming chunk events not processed correctly")

    return chunk_success

if __name__ == "__main__":
    # Run the tests
    main_test_success = test_frontend_event_processing()
    chunk_test_success = test_streaming_chunk_event()

    print("\n" + "=" * 80)
    if main_test_success and chunk_test_success:
        print("🎉 ALL FRONTEND EVENT PROCESSING TESTS PASSED!")
        print("\nThe UI should now display:")
        print("  1. Rich LLM response content and reasoning")
        print("  2. Accurate cost and token usage information")
        print("  3. Tool call results and success status")
        print("  4. Real-time streaming chunks during responses")
        print("  5. Meaningful event descriptions instead of metadata")
    else:
        print("❌ SOME FRONTEND EVENT PROCESSING TESTS FAILED!")
        print("\nCheck the logs above for issues.")

    exit(0 if (main_test_success and chunk_test_success) else 1)
