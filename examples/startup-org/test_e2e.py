#!/usr/bin/env python3
"""E2E test for startup agent organization.

Tests the full lifecycle: import workspace, create model instances,
assign models, submit tasks with delegation and human escalation.

Usage:
    export AGENTAREA_API_KEY=aat_xxx
    export OPENROUTER_API_KEY=sk-or-xxx
    python examples/startup-org/test_e2e.py
"""

import json
import os
import sys
import time
from pathlib import Path

import requests

# --- Configuration ---

API_URL = os.getenv("AGENTAREA_API_URL", "http://localhost:8000")
API_KEY = os.getenv("AGENTAREA_API_KEY")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
WORKSPACE_ID = os.getenv("AGENTAREA_WORKSPACE_ID")

YAML_PATH = Path(__file__).parent / "agents.yaml"

# OpenRouter provider spec ID (from providers.yaml)
OPENROUTER_SPEC_ID = "2531cc11-f35b-43a4-91ba-6bc405dde305"

# Model instance ID to use for all agents (must be a valid UUID from /v1/model-instances/)
# Override with AGENTAREA_MODEL_INSTANCE_ID env var
MODEL_INSTANCE_ID = os.getenv("AGENTAREA_MODEL_INSTANCE_ID")


def headers():
    h = {"Authorization": f"Bearer {API_KEY}", "Content-Type": "application/json"}
    if WORKSPACE_ID:
        h["X-Workspace-ID"] = WORKSPACE_ID
    return h


def step(name):
    print(f"\n{'='*60}")
    print(f"  {name}")
    print(f"{'='*60}")


def ok(msg):
    print(f"  [OK] {msg}")


def fail(msg):
    print(f"  [FAIL] {msg}")
    sys.exit(1)


def warn(msg):
    print(f"  [WARN] {msg}")


# --- Step 1: Import workspace ---

def import_workspace():
    step("1. Import workspace YAML")

    yaml_content = YAML_PATH.read_text()

    # Replace placeholders
    yaml_content = yaml_content.replace("<YOUR_OPENROUTER_API_KEY>", OPENROUTER_API_KEY or "skip-provider-import")
    yaml_content = yaml_content.replace("<YOUR_GITHUB_TOKEN>", "placeholder-not-needed-for-test")
    yaml_content = yaml_content.replace("<YOUR_BRAVE_API_KEY>", "placeholder-not-needed-for-test")

    resp = requests.post(
        f"{API_URL}/v1/workspace/import",
        headers=headers(),
        json={
            "yaml_content": yaml_content,
            "skip_missing_dependencies": True,
            "override_existing": True,
        },
    )

    if resp.status_code != 200:
        fail(f"Import failed ({resp.status_code}): {resp.text}")

    result = resp.json()
    ok(f"Skills: {result.get('created_skills', 0)}")
    ok(f"Agents: {result.get('created_agents', 0)}")
    ok(f"MCP instances: {result.get('created_mcp_instances', 0)}")
    ok(f"Provider configs: {result.get('created_provider_configs', 0)}")

    if result.get("warnings"):
        for w in result["warnings"]:
            warn(w)

    if result.get("errors"):
        for e in result["errors"]:
            fail(e)

    return result


# --- Step 2: Verify agents ---

def verify_agents():
    step("2. Verify agents")

    resp = requests.get(f"{API_URL}/v1/agents/", headers=headers())
    if resp.status_code != 200:
        fail(f"List agents failed ({resp.status_code}): {resp.text}")

    agents = resp.json()
    agent_map = {}

    for agent in agents:
        name = agent["name"]
        agent_map[name] = agent
        agent_type = agent.get("agent_type", "unknown")
        tools = agent.get("tools") or []
        tool_summary = ", ".join(f"{t['type']}:{t['name']}" for t in tools) or "none"
        ok(f"{name} (id={agent['id'][:8]}..., type={agent_type}, tools=[{tool_summary}])")

    expected = {
        "CEO", "Product Manager", "Lead Engineer", "Backend Developer",
        "Frontend Developer", "DevOps Engineer", "QA Engineer", "Marketing Lead",
    }
    found = set(agent_map.keys()) & expected
    missing = expected - found

    if missing:
        warn(f"Missing agents: {missing}")
    else:
        ok(f"All {len(expected)} startup agents found")

    return agent_map


# --- Step 3: Create model instances and assign to agents ---

def setup_models(agent_map):
    step("3. Assign model instance to agents")

    # Find or use provided model instance ID
    model_id = MODEL_INSTANCE_ID

    if not model_id:
        # Auto-discover: use the first active model instance
        resp = requests.get(f"{API_URL}/v1/model-instances/", headers=headers())
        if resp.status_code == 200 and resp.json():
            instances = resp.json()
            model_id = instances[0]["id"]
            ok(f"Auto-selected model instance: {instances[0]['name']} ({model_id[:12]}...)")
        else:
            fail("No model instances found. Create one first via the UI or API.")

    expected_agents = {
        "CEO", "Product Manager", "Lead Engineer", "Backend Developer",
        "Frontend Developer", "DevOps Engineer", "QA Engineer", "Marketing Lead",
    }

    for agent_name in expected_agents:
        if agent_name not in agent_map:
            warn(f"Agent '{agent_name}' not found, skipping")
            continue

        agent_id = agent_map[agent_name]["id"]

        resp = requests.patch(
            f"{API_URL}/v1/agents/{agent_id}",
            headers=headers(),
            json={"model_id": model_id},
        )
        if resp.status_code == 200:
            ok(f"{agent_name} -> {model_id[:12]}...")
        else:
            warn(f"Failed to assign model to {agent_name}: {resp.text[:100]}")


# --- Step 4: Delegation test ---

def test_delegation(agent_map):
    step("4. Delegation test — CEO delegates to engineering")

    ceo = agent_map.get("CEO")
    if not ceo:
        warn("CEO agent not found, skipping delegation test")
        return

    ceo_id = ceo["id"]

    # Submit task to CEO (sync endpoint for simplicity)
    resp = requests.post(
        f"{API_URL}/v1/agents/{ceo_id}/tasks/sync",
        headers=headers(),
        json={
            "description": (
                "We need to add user notifications to our product. "
                "Briefly outline what's needed and delegate the technical planning "
                "to the Lead Engineer."
            ),
        },
    )

    if resp.status_code != 200:
        warn(f"Task creation failed ({resp.status_code}): {resp.text}")
        return

    task = resp.json()
    task_id = task["id"]
    ok(f"Task created: {task_id[:8]}... status={task['status']}")

    if task.get("execution_id"):
        ok(f"Execution ID: {task['execution_id']}")

    # Poll task status and look for delegation events
    poll_task_events(ceo_id, task_id)


def poll_task_events(agent_id, task_id, max_wait=60):
    """Poll task events looking for delegation and completion."""
    start = time.time()
    seen_events = set()

    while time.time() - start < max_wait:
        resp = requests.get(
            f"{API_URL}/v1/agents/{agent_id}/tasks/{task_id}/events",
            headers=headers(),
            params={"page_size": 100},
        )

        if resp.status_code != 200:
            time.sleep(2)
            continue

        data = resp.json()
        events = data.get("events", [])

        for event in events:
            event_id = event.get("id", "")
            if event_id in seen_events:
                continue
            seen_events.add(event_id)

            event_type = event.get("event_type", "")
            message = event.get("message", "")

            if "Delegation" in event_type or "delegation" in message.lower():
                ok(f"DELEGATION EVENT: {event_type} — {message}")
            elif "Approval" in event_type:
                ok(f"ESCALATION EVENT: {event_type} — {message}")
            elif event_type in ("task_completed", "workflow_completed", "WorkflowCompleted"):
                ok(f"COMPLETED: {event_type}")
                return
            elif event_type in ("task_failed", "workflow_failed", "WorkflowFailed"):
                warn(f"FAILED: {event_type} — {message}")
                return

        # Check task status
        status_resp = requests.get(
            f"{API_URL}/v1/agents/{agent_id}/tasks/{task_id}/status",
            headers=headers(),
        )
        if status_resp.status_code == 200:
            status = status_resp.json().get("status", "")
            if status in ("completed", "failed", "cancelled"):
                ok(f"Task reached terminal state: {status}")
                result = status_resp.json().get("result")
                if result:
                    ok(f"Result preview: {str(result)[:200]}...")
                return

        time.sleep(3)

    warn(f"Timed out after {max_wait}s — task may still be running")


# --- Step 5: Escalation test ---

def test_escalation(agent_map):
    step("5. Escalation test — DevOps deployment requires approval")

    devops = agent_map.get("DevOps Engineer")
    if not devops:
        warn("DevOps Engineer not found, skipping escalation test")
        return

    devops_id = devops["id"]

    # Submit task that should trigger tool with requires_user_confirmation
    resp = requests.post(
        f"{API_URL}/v1/agents/{devops_id}/tasks/sync",
        headers=headers(),
        json={
            "description": "Check the current Docker containers running in production.",
            "requires_human_approval": True,
        },
    )

    if resp.status_code != 200:
        warn(f"Task creation failed ({resp.status_code}): {resp.text}")
        return

    task = resp.json()
    task_id = task["id"]
    ok(f"Task created: {task_id[:8]}... status={task['status']}")

    # Poll for escalation event
    start = time.time()
    max_wait = 30

    while time.time() - start < max_wait:
        status_resp = requests.get(
            f"{API_URL}/v1/agents/{devops_id}/tasks/{task_id}/status",
            headers=headers(),
        )

        if status_resp.status_code == 200:
            status_data = status_resp.json()
            status = status_data.get("status", "")

            if status == "waiting_for_approval":
                ok("Task is waiting for human approval!")

                # Auto-approve for testing
                events_resp = requests.get(
                    f"{API_URL}/v1/agents/{devops_id}/tasks/{task_id}/events",
                    headers=headers(),
                    params={"page_size": 100},
                )

                if events_resp.status_code == 200:
                    events = events_resp.json().get("events", [])
                    for event in events:
                        metadata = event.get("metadata", {})
                        escalation_id = metadata.get("escalation_id")
                        if escalation_id:
                            ok(f"Found escalation: {escalation_id[:8]}...")

                            # Resolve it
                            resolve_resp = requests.post(
                                f"{API_URL}/v1/agents/{devops_id}/tasks/{task_id}/resolve-escalation",
                                headers=headers(),
                                json={
                                    "escalation_id": escalation_id,
                                    "approved": True,
                                    "comment": "Auto-approved by e2e test",
                                },
                            )

                            if resolve_resp.status_code == 200:
                                ok("Escalation approved! Workflow should continue.")
                            else:
                                warn(f"Resolve failed: {resolve_resp.text}")
                            break

                # Continue polling for completion
                poll_task_events(devops_id, task_id, max_wait=30)
                return

            elif status in ("completed", "failed", "cancelled"):
                ok(f"Task completed with status: {status}")
                return

        time.sleep(2)

    warn(f"No escalation event seen within {max_wait}s")
    poll_task_events(devops_id, task_id, max_wait=15)


# --- Main ---

def main():
    print("\n" + "=" * 60)
    print("  Startup Agent Organization — E2E Test")
    print("=" * 60)

    # Validate env vars
    if not API_KEY:
        fail("AGENTAREA_API_KEY not set")

    ok(f"API URL: {API_URL}")
    ok("API Key: configured")
    if OPENROUTER_API_KEY:
        ok("OpenRouter Key: configured")
    else:
        ok("OpenRouter Key: not set (using existing provider config in DB)")

    # Health check
    try:
        resp = requests.get(f"{API_URL}/health", timeout=5)
        if resp.status_code != 200:
            fail(f"API health check failed: {resp.status_code}")
        ok("API is healthy")
    except requests.ConnectionError:
        fail(f"Cannot connect to {API_URL}")

    # Run steps
    import_workspace()
    agent_map = verify_agents()
    setup_models(agent_map)
    test_delegation(agent_map)
    test_escalation(agent_map)

    step("DONE")
    ok("E2E test completed. Check results above for delegation and escalation events.")


if __name__ == "__main__":
    main()
