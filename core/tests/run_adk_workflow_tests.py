#!/usr/bin/env python3
"""
Script to run ADK workflow tests.

This script provides an easy way to run the ADK workflow tests with proper setup.
"""

import asyncio
import logging
import os
import subprocess
import sys
from pathlib import Path

# Add core to Python path
core_dir = Path(__file__).parent.parent
sys.path.insert(0, str(core_dir))

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


def check_temporal_server():
    """Check if Temporal server is running."""
    import socket

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(2)
        result = sock.connect_ex(("localhost", 7233))
        sock.close()
        return result == 0
    except Exception:
        return False


def check_database():
    """Check if database is accessible."""
    try:
        import asyncpg

        async def check_db():
            try:
                conn = await asyncpg.connect(
                    host="localhost",
                    port=5432,
                    user="postgres",
                    password="postgres",
                    database="aiagents",
                )
                await conn.close()
                return True
            except Exception:
                return False

        return asyncio.run(check_db())
    except ImportError:
        logger.warning("asyncpg not available, skipping database check")
        return True


def run_unit_tests():
    """Run unit tests."""
    logger.info("🧪 Running unit tests...")

    test_file = core_dir / "tests" / "unit" / "test_adk_agent_workflow_unit.py"

    cmd = [sys.executable, "-m", "pytest", str(test_file), "-v", "-m", "unit", "--tb=short"]

    result = subprocess.run(cmd, cwd=core_dir)
    return result.returncode == 0


def run_integration_tests():
    """Run integration tests."""
    logger.info("🔗 Running integration tests...")

    # Check prerequisites
    if not check_temporal_server():
        logger.error("❌ Temporal server not running on localhost:7233")
        logger.info("   Start Temporal with: temporal server start-dev")
        return False

    if not check_database():
        logger.error("❌ Database not accessible")
        logger.info("   Start database with: docker-compose -f docker-compose.dev.yaml up db -d")
        return False

    logger.info("✅ Prerequisites check passed")

    test_file = core_dir / "tests" / "integration" / "test_adk_agent_workflow_comprehensive.py"

    cmd = [
        sys.executable,
        "-m",
        "pytest",
        str(test_file),
        "-v",
        "-m",
        "integration",
        "--tb=short",
        "-x",  # Stop on first failure
    ]

    # Set environment variables
    env = os.environ.copy()
    env["PYTHONPATH"] = str(core_dir)

    result = subprocess.run(cmd, cwd=core_dir, env=env)
    return result.returncode == 0


def run_test_worker():
    """Run the test worker."""
    logger.info("🏃 Running test worker...")

    if not check_temporal_server():
        logger.error("❌ Temporal server not running on localhost:7233")
        return False

    test_worker_file = core_dir / "tests" / "integration" / "test_adk_workflow_worker.py"

    cmd = [sys.executable, str(test_worker_file), "single"]

    # Set environment variables
    env = os.environ.copy()
    env["PYTHONPATH"] = str(core_dir)

    result = subprocess.run(cmd, cwd=core_dir, env=env)
    return result.returncode == 0


def run_math_test():
    """Run the math test."""
    logger.info("🧮 Running math test...")

    if not check_temporal_server():
        logger.error("❌ Temporal server not running on localhost:7233")
        return False

    test_worker_file = core_dir / "tests" / "integration" / "test_adk_workflow_worker.py"

    cmd = [sys.executable, str(test_worker_file), "math"]

    # Set environment variables
    env = os.environ.copy()
    env["PYTHONPATH"] = str(core_dir)

    result = subprocess.run(cmd, cwd=core_dir, env=env)
    return result.returncode == 0


def main():
    """Main entry point."""
    if len(sys.argv) < 2:
        print("Usage:")
        print("  python run_adk_workflow_tests.py unit         # Run unit tests")
        print("  python run_adk_workflow_tests.py integration  # Run integration tests")
        print("  python run_adk_workflow_tests.py worker       # Run test worker")
        print("  python run_adk_workflow_tests.py math         # Run math test")
        print("  python run_adk_workflow_tests.py all          # Run all tests")
        sys.exit(1)

    test_type = sys.argv[1].lower()

    success = True

    try:
        if test_type == "unit":
            success = run_unit_tests()
        elif test_type == "integration":
            success = run_integration_tests()
        elif test_type == "worker":
            success = run_test_worker()
        elif test_type == "math":
            success = run_math_test()
        elif test_type == "all":
            logger.info("🎯 Running all tests...")
            success = (
                run_unit_tests()
                and run_integration_tests()
                and run_test_worker()
                and run_math_test()
            )
        else:
            logger.error(f"❌ Unknown test type: {test_type}")
            sys.exit(1)

        if success:
            logger.info("🎉 All tests completed successfully!")
        else:
            logger.error("❌ Some tests failed")
            sys.exit(1)

    except KeyboardInterrupt:
        logger.info("⌨️ Interrupted by user")
        sys.exit(1)
    except Exception as e:
        logger.error(f"❌ Test runner error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
