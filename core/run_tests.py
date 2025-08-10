#!/usr/bin/env python3
"""Test runner script for AgentArea workflow activities and task events.

This script demonstrates how to run the tests for the new TaskEvent
functionality and workflow activities.
"""

import os
import subprocess
import sys


def run_command(command, description):
    """Run a command and handle the result."""
    print(f"\n{'='*60}")
    print(f"Running: {description}")
    print(f"Command: {command}")
    print('='*60)

    try:
        result = subprocess.run(
            command,
            shell=True,
            check=True,
            capture_output=True,
            text=True,
            cwd=os.path.dirname(__file__)
        )

        print("✅ SUCCESS")
        if result.stdout:
            print("STDOUT:")
            print(result.stdout)

        return True

    except subprocess.CalledProcessError as e:
        print("❌ FAILED")
        print(f"Exit code: {e.returncode}")
        if e.stdout:
            print("STDOUT:")
            print(e.stdout)
        if e.stderr:
            print("STDERR:")
            print(e.stderr)

        return False


def main():
    """Run all tests for the workflow activities and task events."""
    print("🧪 AgentArea Workflow Activities & Task Events Test Suite")
    print("=" * 60)

    # Test commands to run
    test_commands = [
        {
            "command": "uv run pytest tests/unit/test_task_event_service.py -v",
            "description": "Unit tests for TaskEventService"
        },
        {
            "command": "uv run pytest tests/unit/test_workflow_activities.py -v",
            "description": "Unit tests for Workflow Activities"
        },
        {
            "command": "uv run pytest tests/integration/test_task_event_integration.py -v -m 'not integration'",
            "description": "Integration tests for TaskEvent (mocked DB)"
        },
        {
            "command": "uv run pytest tests/unit/ -v --tb=short",
            "description": "All unit tests with short traceback"
        }
    ]

    # Run each test command
    results = []
    for test_config in test_commands:
        success = run_command(test_config["command"], test_config["description"])
        results.append((test_config["description"], success))

    # Summary
    print(f"\n{'='*60}")
    print("📊 TEST SUMMARY")
    print('='*60)

    passed = 0
    failed = 0

    for description, success in results:
        status = "✅ PASSED" if success else "❌ FAILED"
        print(f"{status}: {description}")
        if success:
            passed += 1
        else:
            failed += 1

    print(f"\nTotal: {len(results)} test suites")
    print(f"Passed: {passed}")
    print(f"Failed: {failed}")

    if failed > 0:
        print("\n⚠️  Some tests failed. Check the output above for details.")
        return 1
    else:
        print("\n🎉 All tests passed!")
        return 0


if __name__ == "__main__":
    sys.exit(main())
