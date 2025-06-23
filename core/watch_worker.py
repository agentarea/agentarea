#!/usr/bin/env python3
"""
Auto-restart Temporal worker on file changes using watchfiles.
"""
import subprocess
import sys

def main():
    """Run the Temporal worker with auto-restart on file changes."""
    print("🚀 Starting Temporal worker with auto-restart...")
    print("📝 Watching for Python file changes in apps/worker and libs directories")
    print("Press Ctrl+C to stop")
    
    try:
        # Run watchfiles to monitor and restart the worker
        # Correct syntax: watchfiles 'command' path1 path2 path3
        subprocess.run([
            sys.executable, "-m", "watchfiles",
            "python apps/worker/agentarea_worker/main.py",
            "apps/worker",
            "libs",
            "--verbose"
        ])
    except KeyboardInterrupt:
        print("\n✅ Worker auto-restart stopped")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main() 