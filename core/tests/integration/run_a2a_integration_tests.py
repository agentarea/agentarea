#!/usr/bin/env python3
"""Test runner for A2A integration tests.

This script runs the comprehensive A2A task execution integration tests
and provides a summary of the results.
"""

import asyncio
import sys
from pathlib import Path

# Add the core directory to the Python path
core_dir = Path(__file__).parent.parent.parent
sys.path.insert(0, str(core_dir))

from tests.integration.test_a2a_task_execution_comprehensive import (
    test_a2a_authentication_failures,
    test_a2a_error_scenarios,
    test_a2a_jsonrpc_protocol_compliance,
    test_a2a_message_send_creates_temporal_task,
    test_a2a_task_creation_through_jsonrpc,
    test_a2a_task_management_endpoints,
    test_a2a_task_streaming_with_real_events,
    test_a2a_task_workflow_status_integration,
)


async def run_all_tests():
    """Run all A2A integration tests."""
    tests = [
        ("A2A Task Creation through JSON-RPC", test_a2a_task_creation_through_jsonrpc),
        ("A2A Message Send creates Temporal Task", test_a2a_message_send_creates_temporal_task),
        ("A2A Task Streaming with Real Events", test_a2a_task_streaming_with_real_events),
        ("A2A Task Management Endpoints", test_a2a_task_management_endpoints),
        ("A2A Authentication Failures", test_a2a_authentication_failures),
        ("A2A Error Scenarios", test_a2a_error_scenarios),
        ("A2A JSON-RPC Protocol Compliance", test_a2a_jsonrpc_protocol_compliance),
        ("A2A Task Workflow Status Integration", test_a2a_task_workflow_status_integration),
    ]

    passed = 0
    failed = 0

    print("🚀 Running A2A Integration Tests")
    print("=" * 50)

    for test_name, test_func in tests:
        try:
            print(f"Running: {test_name}...", end=" ")
            await test_func()
            print("✅ PASSED")
            passed += 1
        except Exception as e:
            print(f"❌ FAILED: {e}")
            failed += 1

    print("=" * 50)
    print(f"Results: {passed} passed, {failed} failed")

    if failed == 0:
        print("🎉 All A2A integration tests passed!")
        return True
    else:
        print("💥 Some tests failed!")
        return False


if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    sys.exit(0 if success else 1)
