#!/usr/bin/env python3
"""
Test runner for trigger system integration tests.

This script runs all trigger system integration tests and provides
comprehensive reporting on test results and system validation.
"""

import os
import sys
import time
from pathlib import Path

# Add the core directory to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest


def main():
    """Run trigger system integration tests."""
    print("=" * 80)
    print("TRIGGER SYSTEM INTEGRATION TEST RUNNER")
    print("=" * 80)

    # Test configuration
    test_args = [
        "-v",  # Verbose output
        "--tb=short",  # Short traceback format
        "-x",  # Stop on first failure
        "--asyncio-mode=auto",  # Enable asyncio mode
        "--disable-warnings",  # Disable warnings for cleaner output
    ]

    # Test discovery patterns
    test_patterns = [
        "core/tests/integration/test_trigger_e2e_scenarios.py",
        "core/tests/integration/test_trigger_webhook_http_integration.py",
        "core/tests/integration/test_trigger_lifecycle_management.py",
        "core/tests/integration/test_trigger_safety_integration.py",
        "core/tests/integration/test_trigger_performance_concurrent.py",
        "core/tests/integration/test_trigger_comprehensive_suite.py",
    ]

    # Check if trigger system is available
    try:
        from agentarea_triggers.trigger_service import TriggerService

        print("✓ Trigger system components available")
    except ImportError as e:
        print(f"✗ Trigger system not available: {e}")
        print("Skipping trigger integration tests")
        return 0

    # Run tests for each category
    categories = [
        ("End-to-End Scenarios", "test_trigger_e2e_scenarios.py"),
        ("Webhook HTTP Integration", "test_trigger_webhook_http_integration.py"),
        ("Lifecycle Management", "test_trigger_lifecycle_management.py"),
        ("Safety Mechanisms", "test_trigger_safety_integration.py"),
        ("Performance & Concurrency", "test_trigger_performance_concurrent.py"),
        ("Comprehensive Suite", "test_trigger_comprehensive_suite.py"),
    ]

    overall_results = {
        "total_categories": len(categories),
        "passed_categories": 0,
        "failed_categories": 0,
        "total_time": 0,
    }

    start_time = time.time()

    for category_name, test_file in categories:
        print(f"\n{'=' * 60}")
        print(f"RUNNING: {category_name}")
        print(f"{'=' * 60}")

        test_path = f"core/tests/integration/{test_file}"

        if not os.path.exists(test_path):
            print(f"✗ Test file not found: {test_path}")
            overall_results["failed_categories"] += 1
            continue

        category_start = time.time()

        # Run tests for this category
        result = pytest.main(
            [*test_args, test_path, f"--junit-xml=test_results_{test_file.replace('.py', '')}.xml"]
        )

        category_end = time.time()
        category_time = category_end - category_start

        if result == 0:
            print(f"✓ {category_name} - PASSED ({category_time:.2f}s)")
            overall_results["passed_categories"] += 1
        else:
            print(f"✗ {category_name} - FAILED ({category_time:.2f}s)")
            overall_results["failed_categories"] += 1

    end_time = time.time()
    overall_results["total_time"] = end_time - start_time

    # Print final summary
    print(f"\n{'=' * 80}")
    print("TRIGGER INTEGRATION TEST SUMMARY")
    print(f"{'=' * 80}")
    print(f"Total Categories: {overall_results['total_categories']}")
    print(f"Passed Categories: {overall_results['passed_categories']}")
    print(f"Failed Categories: {overall_results['failed_categories']}")
    print(f"Total Execution Time: {overall_results['total_time']:.2f}s")

    if overall_results["failed_categories"] == 0:
        print("\n🎉 ALL TRIGGER INTEGRATION TESTS PASSED!")
        print("✅ Trigger system is ready for production")
        return_code = 0
    else:
        print(f"\n❌ {overall_results['failed_categories']} CATEGORIES FAILED")
        print("🔧 Please review and fix failing tests")
        return_code = 1

    print(f"{'=' * 80}")

    return return_code


if __name__ == "__main__":
    sys.exit(main())
