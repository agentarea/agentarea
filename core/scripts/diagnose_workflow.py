#!/usr/bin/env python3
"""Diagnostic tool for troubleshooting workflow execution issues."""

import asyncio
import json
import sys
from datetime import datetime, timedelta
from typing import Any

from temporalio.client import Client
from temporalio.contrib.pydantic import pydantic_data_converter


async def diagnose_workflow(workflow_id: str, namespace: str = "default") -> dict[str, Any]:
    """Diagnose a workflow execution to identify why it might not be finishing."""
    client = await Client.connect(
        "localhost:7233", namespace=namespace, data_converter=pydantic_data_converter
    )

    try:
        # Get workflow handle
        handle = client.get_workflow_handle(workflow_id)

        # Get workflow description
        description = await handle.describe()

        # Get workflow history
        history_events = []
        async for event in handle.fetch_history():
            history_events.append(
                {
                    "event_id": event.event_id,
                    "event_type": event.event_type.name,
                    "timestamp": event.event_time.isoformat() if event.event_time else None,
                }
            )

        # Analyze workflow state
        diagnosis = {
            "workflow_id": workflow_id,
            "status": description.status.name,
            "start_time": description.start_time.isoformat() if description.start_time else None,
            "execution_time": str(datetime.now() - description.start_time)
            if description.start_time
            else None,
            "task_queue": description.task_queue,
            "workflow_type": description.workflow_type,
            "run_id": description.run_id,
            "history_length": len(history_events),
            "recent_events": history_events[-10:] if history_events else [],
        }

        # Try to query current state if workflow is running
        if description.status.name == "RUNNING":
            try:
                current_state = await handle.query("get_current_state")
                diagnosis["current_state"] = current_state

                # Get latest events
                latest_events = await handle.query("get_latest_events", 20)
                diagnosis["latest_workflow_events"] = latest_events

            except Exception as e:
                diagnosis["query_error"] = str(e)

        # Analyze potential issues
        issues = []

        if description.status.name == "RUNNING":
            if description.start_time:
                runtime = datetime.now() - description.start_time
                if runtime > timedelta(minutes=30):
                    issues.append(f"Workflow has been running for {runtime} - possibly stuck")

        if len(history_events) > 1000:
            issues.append(
                f"Very long history ({len(history_events)} events) - possible infinite loop"
            )

        # Check for repeated patterns in recent events
        recent_event_types = [e["event_type"] for e in history_events[-50:]]
        if len(set(recent_event_types)) < 5 and len(recent_event_types) > 20:
            issues.append("Detected repetitive event pattern - possible infinite loop")

        diagnosis["potential_issues"] = issues

        return diagnosis

    except Exception as e:
        return {"workflow_id": workflow_id, "error": str(e), "error_type": type(e).__name__}
    finally:
        await client.close()


async def main():
    """Main diagnostic function."""
    if len(sys.argv) < 2:
        print("Usage: python diagnose_workflow.py <workflow_id> [namespace]")
        sys.exit(1)

    workflow_id = sys.argv[1]
    namespace = sys.argv[2] if len(sys.argv) > 2 else "default"

    print(f"Diagnosing workflow: {workflow_id}")
    print(f"Namespace: {namespace}")
    print("-" * 50)

    diagnosis = await diagnose_workflow(workflow_id, namespace)

    print(json.dumps(diagnosis, indent=2, default=str))

    if diagnosis.get("potential_issues"):
        print("\n🚨 POTENTIAL ISSUES DETECTED:")
        for issue in diagnosis["potential_issues"]:
            print(f"  - {issue}")

    if diagnosis.get("current_state"):
        state = diagnosis["current_state"]
        print("\n📊 CURRENT STATE:")
        print(f"  - Status: {state.get('status', 'unknown')}")
        print(f"  - Iteration: {state.get('current_iteration', 0)}")
        print(f"  - Success: {state.get('success', False)}")
        print(f"  - Cost: ${state.get('cost', 0):.4f}")
        print(f"  - Budget Remaining: ${state.get('budget_remaining', 0):.4f}")
        print(f"  - Paused: {state.get('paused', False)}")


if __name__ == "__main__":
    asyncio.run(main())
