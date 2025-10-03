#!/usr/bin/env python3
"""Test runner for comprehensive workspace isolation test suite."""

import subprocess
import sys
from pathlib import Path


def run_test_suite():
    """Run the comprehensive workspace isolation test suite."""

    test_files = [
        "tests/unit/test_workspace_scoped_repository_comprehensive.py",
        "tests/unit/test_jwt_token_extraction_comprehensive.py",
        "tests/unit/test_workspace_error_handling.py",
        "tests/integration/test_workspace_data_isolation.py",
        "tests/integration/test_cross_workspace_access_prevention.py",
        "tests/integration/test_workspace_isolation_comprehensive.py",
    ]

    print("🚀 Running Comprehensive Workspace Isolation Test Suite")
    print("=" * 60)

    total_passed = 0
    total_failed = 0
    failed_files = []

    for test_file in test_files:
        print(f"\n📋 Running {test_file}")
        print("-" * 40)

        try:
            result = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    test_file,
                    "-v",
                    "--tb=short",
                    "--disable-warnings",
                ],
                capture_output=True,
                text=True,
                cwd=Path(__file__).parent,
            )

            if result.returncode == 0:
                print(f"✅ {test_file} - ALL TESTS PASSED")
                # Count passed tests from output
                lines = result.stdout.split("\n")
                for line in lines:
                    if "passed" in line and "failed" not in line:
                        try:
                            passed = int(line.split()[0])
                            total_passed += passed
                            break
                        except (ValueError, IndexError):
                            continue
            else:
                print(f"❌ {test_file} - SOME TESTS FAILED")
                failed_files.append(test_file)
                # Count failed and passed tests
                lines = result.stdout.split("\n")
                for line in lines:
                    if "failed" in line and "passed" in line:
                        try:
                            parts = line.split()
                            failed = int(parts[0])
                            passed_idx = parts.index("passed,") - 1
                            passed = int(parts[passed_idx])
                            total_failed += failed
                            total_passed += passed
                            break
                        except (ValueError, IndexError):
                            continue

                print("STDERR:", result.stderr)
                print("STDOUT:", result.stdout[-1000:])  # Last 1000 chars

        except Exception as e:
            print(f"💥 Error running {test_file}: {e}")
            failed_files.append(test_file)

    print("\n" + "=" * 60)
    print("📊 FINAL RESULTS")
    print("=" * 60)
    print(f"✅ Total Passed: {total_passed}")
    print(f"❌ Total Failed: {total_failed}")
    print(f"📁 Files with failures: {len(failed_files)}")

    if failed_files:
        print("\n🔍 Files that need attention:")
        for file in failed_files:
            print(f"  - {file}")

    if total_failed == 0:
        print("\n🎉 ALL WORKSPACE ISOLATION TESTS PASSED!")
        print("✨ The workspace isolation system is working correctly!")
        return True
    else:
        print(f"\n⚠️  {total_failed} tests failed. Please review and fix.")
        return False


if __name__ == "__main__":
    success = run_test_suite()
    sys.exit(0 if success else 1)
