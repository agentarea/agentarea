#!/usr/bin/env python3
"""Start the API server and open the SSE test UI."""

import subprocess
import sys
import time
import webbrowser
from pathlib import Path


def start_api_server():
    """Start the FastAPI server."""
    print("🚀 Starting AgentArea API server...")

    # Start the API server using the make command
    try:
        process = subprocess.Popen(
            ["make", "run-api"],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True,
        )

        print("⏳ Waiting for API server to start...")

        # Wait for server to start by looking for startup message
        startup_detected = False
        for line in process.stdout:
            print(f"[API] {line.strip()}")
            if "Uvicorn running on" in line or "Application startup complete" in line:
                startup_detected = True
                break
            if "ERROR" in line or "FAILED" in line:
                print(f"❌ API server startup failed: {line}")
                return None

        if startup_detected:
            print("✅ API server started successfully!")
            return process
        else:
            print("⚠️  API server startup status unclear, but proceeding...")
            return process

    except FileNotFoundError:
        print("❌ 'make' command not found. Trying direct Python startup...")

        # Fallback: try to start with Python directly
        try:
            process = subprocess.Popen(
                [sys.executable, "cli.py", "serve", "--reload"],
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
            )

            print("⏳ Waiting for direct Python server startup...")
            time.sleep(3)  # Give it a moment to start

            if process.poll() is None:  # Process is still running
                print("✅ API server started with Python!")
                return process
            else:
                print("❌ Failed to start API server with Python")
                return None

        except Exception as e:
            print(f"❌ Failed to start API server: {e}")
            return None

    except Exception as e:
        print(f"❌ Failed to start API server: {e}")
        return None


def open_test_page():
    """Open the SSE test page in the browser."""
    test_page = Path(__file__).parent / "test_real_sse.html"

    if not test_page.exists():
        print(f"❌ Test page not found: {test_page}")
        return False

    try:
        # Open the HTML file in the default browser
        webbrowser.open(f"file://{test_page.absolute()}")
        print(f"🌐 Opened test page in browser: {test_page}")
        return True
    except Exception as e:
        print(f"❌ Failed to open browser: {e}")
        print(f"💡 Manually open: file://{test_page.absolute()}")
        return False


def main():
    """Main function to start everything."""
    print("=" * 60)
    print("🧪 AgentArea SSE Real-Time Testing")
    print("=" * 60)

    # Start the API server
    api_process = start_api_server()

    if not api_process:
        print("❌ Cannot proceed without API server")
        return 1

    try:
        # Give the server a moment to fully start
        time.sleep(2)

        # Open the test page
        print("\n📄 Opening SSE test page...")
        if open_test_page():
            print("\n✅ Test environment ready!")
            print("\n🔧 Instructions:")
            print("1. The API server is running at http://localhost:8000")
            print("2. The test page should open in your browser")
            print("3. Click 'Create Task & Start Streaming' to test real SSE events")
            print("4. Watch real-time events as the workflow executes")
            print("\n⚠️  Note: You need at least one agent configured in the database")
            print("   Use 'python cli.py agent list' to see available agents")
            print("   Use 'python cli.py agent create' to create a test agent")

            print("\n🛑 Press Ctrl+C to stop the API server")

            # Keep the process running
            try:
                api_process.wait()
            except KeyboardInterrupt:
                print("\n🛑 Shutting down...")
                api_process.terminate()
                time.sleep(1)
                if api_process.poll() is None:
                    api_process.kill()
                print("✅ API server stopped")

        else:
            print("❌ Failed to open test page")
            api_process.terminate()
            return 1

    except KeyboardInterrupt:
        print("\n🛑 Shutting down...")
        api_process.terminate()
        time.sleep(1)
        if api_process.poll() is None:
            api_process.kill()
        print("✅ API server stopped")

    except Exception as e:
        print(f"❌ Unexpected error: {e}")
        api_process.terminate()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
