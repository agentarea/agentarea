#!/usr/bin/env python3
"""End-to-end test: Progressive Skill Disclosure via the full API.

Sets up the complete chain:
  1. Provider config with OpenRouter API key
  2. Model instance (using existing llama-3.3-70b model spec)
  3. Two skills (math-methodology + js-formatter)
  4. An agent with both skills
  5. A task that triggers skill activation

Usage:
    cd agentarea-platform
    uv run python tests/e2e_api_skill_disclosure.py
"""

import json
import os
import sys
import time

import httpx
from dotenv import load_dotenv

# Load .env.local from monorepo root
_script_dir = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(_script_dir, "..", "..", ".env.local"))

API = "http://localhost:8000/v1"
TOKEN = "aat_xhymm4Sy6KORfYOSL0vvnCU2G309SkYTkjeGsC2rrm0"
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
OPENROUTER_PROVIDER_SPEC_ID = "2531cc11-f35b-43a4-91ba-6bc405dde305"
LLAMA_MODEL_SPEC_ID = "70b9dd37-2529-42f2-9722-31773ef49494"

HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}
created = {}


def api(method: str, path: str, body: dict | None = None) -> dict | list | None:
    """Make an API call. Adds trailing slash for mutating methods."""
    url = f"{API}{path}"
    if method in ("POST", "PATCH", "PUT") and not url.endswith("/"):
        url += "/"
    with httpx.Client(timeout=60, follow_redirects=True) as client:
        if method == "GET":
            r = client.get(url, headers=HEADERS)
        elif method == "POST":
            r = client.post(url, headers=HEADERS, json=body)
        elif method == "DELETE":
            r = client.delete(url, headers=HEADERS)
            return None
        else:
            raise ValueError(f"Unknown method: {method}")
    if r.status_code >= 400:
        print(f"  ERROR {method} {path}: {r.status_code} {r.text[:300]}")
        return None
    return r.json() if r.text else None


def cleanup():
    """Delete created resources in reverse order."""
    print("\n-- Cleanup --")
    for key, path_prefix in [
        ("agent_id", "/agents/"),
        ("skill_calc_id", "/skills/"),
        ("skill_js_id", "/skills/"),
        ("model_instance_id", "/model-instances/"),
        ("provider_config_id", "/provider-configs/"),
    ]:
        if key in created:
            api("DELETE", f"{path_prefix}{created[key]}")
            print(f"  Deleted {key}: {created[key]}")


def main():
    if not OPENROUTER_API_KEY:
        print("ERROR: OPENROUTER_API_KEY not set")
        sys.exit(1)

    print("=" * 60)
    print("E2E API Test: Progressive Skill Disclosure")
    print("Model: meta-llama/llama-3.3-70b-instruct via OpenRouter")
    print("=" * 60)

    try:
        # ── 1. Provider config ───────────────────────────────────
        print("\n1. Creating provider config...")
        pc = api("POST", "/provider-configs", {
            "provider_spec_id": OPENROUTER_PROVIDER_SPEC_ID,
            "name": "OpenRouter (e2e skill test)",
            "api_key": OPENROUTER_API_KEY,
        })
        assert pc, "Failed to create provider config"
        created["provider_config_id"] = pc["id"]
        print(f"   {pc['id']}")

        # ── 2. Model instance ────────────────────────────────────
        print("\n2. Creating model instance...")
        mi = api("POST", "/model-instances", {
            "provider_config_id": pc["id"],
            "model_spec_id": LLAMA_MODEL_SPEC_ID,
            "name": "Llama 3.3 70B (e2e skill test)",
        })
        assert mi, "Failed to create model instance"
        created["model_instance_id"] = mi["id"]
        print(f"   {mi['id']}")

        # ── 3. Skills ────────────────────────────────────────────
        print("\n3. Creating skills...")
        s1 = api("POST", "/skills", {
            "name": "math-methodology",
            "description": "Step-by-step methodology for solving math problems with verification",
            "content": (
                "---\nname: math-methodology\n"
                "description: Step-by-step methodology for solving math problems with verification\n"
                "---\n\n"
                "## Math Problem Solving Methodology\n\n"
                "When solving math problems, follow these steps:\n"
                "1. Break the expression into parts\n"
                "2. Solve each part step by step\n"
                "3. Verify by working backwards\n"
                "4. State the final answer clearly as: ANSWER: <number>\n\n"
                "Always show your work. Never skip verification."
            ),
        })
        assert s1, "Failed to create math-methodology skill"
        created["skill_calc_id"] = s1["id"]
        print(f"   math-methodology: {s1['id']}")

        s2 = api("POST", "/skills", {
            "name": "js-formatter",
            "description": "Format and lint JavaScript/TypeScript code with Prettier",
            "content": (
                "---\nname: js-formatter\n"
                "description: Format and lint JavaScript/TypeScript code with Prettier\n"
                "---\n\nUse prettier to format JS/TS files."
            ),
        })
        assert s2, "Failed to create js-formatter skill"
        created["skill_js_id"] = s2["id"]
        print(f"   js-formatter:     {s2['id']}")

        # ── 4. Agent ─────────────────────────────────────────────
        print("\n4. Creating agent with 2 skills...")
        agent = api("POST", "/agents", {
            "name": "E2E Skill Disclosure Agent",
            "description": "Tests progressive skill disclosure",
            "instruction": (
                "You are a helpful agent. You MUST use the activate_skill tool to load "
                "skill instructions before attempting any task. Check the Available Skills "
                "catalog and activate the matching skill first, then follow its methodology."
            ),
            "model_id": mi["id"],
            "skill_ids": [s1["id"], s2["id"]],
            "tools": [],
        })
        assert agent, "Failed to create agent"
        created["agent_id"] = agent["id"]
        print(f"   {agent['id']}")

        # ── 5. Run task (sync) ───────────────────────────────────
        print("\n5. Creating task...")
        task = api("POST", f"/agents/{agent['id']}/tasks/sync", {
            "description": "Solve this math problem: What is 42 * 17 + 99? Activate the appropriate skill first.",
        })
        if not task:
            print("  WARN: sync endpoint failed, trying SSE...")
            # Fall back to SSE endpoint and just wait
            task = api("POST", f"/agents/{agent['id']}/tasks", {
                "description": "What is 42 * 17? Use the calculator tool.",
            })
        task_id = task.get("id") if task else None
        print(f"   Task: {task_id}")
        print(f"   Status: {task.get('status') if task else 'unknown'}")

        # ── 6. Poll for completion ───────────────────────────────
        print("\n6. Waiting for completion...")
        final_status = None
        for i in range(60):
            time.sleep(3)
            status = api("GET", f"/agents/{agent['id']}/tasks/{task_id}/status")
            if not status:
                print(f"   [{i*3}s] Could not get status")
                continue
            s = status.get("status", "unknown")
            if s in ("completed", "failed", "cancelled"):
                final_status = s
                result = status.get("result") or status.get("message", "")
                print(f"   [{i*3}s] {s}: {str(result)[:200]}")
                break
            elif i % 5 == 0:
                print(f"   [{i*3}s] {s}...")

        # ── 7. Get task events ───────────────────────────────────
        print("\n7. Fetching task events...")
        events = api("GET", f"/agents/{agent['id']}/tasks/{task_id}/events?page_size=100")
        event_list = events.get("events", []) if events else []
        print(f"   Total events: {len(event_list)}")

        # Analyze events
        tool_events = [
            e for e in event_list
            if e.get("event_type") == "ToolCallCompleted"
        ]
        skill_events = [
            e for e in tool_events
            if e.get("metadata", {}).get("tool_name") == "activate_skill"
        ]
        other_tool_events = [
            e for e in tool_events
            if e.get("metadata", {}).get("tool_name") not in ("activate_skill", "completion")
        ]

        print(f"   Tool calls: {len(tool_events)}")
        for e in tool_events:
            m = e.get("metadata", {})
            print(f"     - {m.get('tool_name', '?')} (skill: {m.get('skill_name', 'n/a')})")

        # ── 8. Verdict ───────────────────────────────────────────
        print("\n" + "=" * 60)
        print("RESULTS")
        print("=" * 60)

        passed = 0
        total = 4

        # Check 1: activate_skill was called
        if skill_events:
            activated = [e["metadata"].get("skill_name") for e in skill_events]
            print(f"\n  PASS: activate_skill called for: {activated}")
            passed += 1
        else:
            print("\n  FAIL: activate_skill was NOT called")

        # Check 2: math-methodology specifically
        calc_activated = any(
            e.get("metadata", {}).get("skill_name") == "math-methodology"
            for e in skill_events
        )
        if calc_activated:
            print("  PASS: math-methodology activated (correct)")
            passed += 1
        else:
            print("  FAIL: math-methodology NOT activated")

        # Check 3: js-formatter NOT activated
        js_activated = any(
            e.get("metadata", {}).get("skill_name") == "js-formatter"
            for e in skill_events
        )
        if not js_activated:
            print("  PASS: js-formatter NOT activated (correctly skipped)")
            passed += 1
        else:
            print("  FAIL: js-formatter was activated (should have been skipped)")

        # Check 4: task completed
        if final_status == "completed":
            print("  PASS: Task completed")
            passed += 1
        else:
            print(f"  FAIL: Task status: {final_status}")

        print(f"\n  Score: {passed}/{total}")

        if "--verbose" in sys.argv:
            print("\n-- All events --")
            for e in event_list:
                meta = json.dumps(e.get("metadata", {}))[:150]
                print(f"  [{e.get('event_type')}] {meta}")

    finally:
        cleanup()


if __name__ == "__main__":
    main()
