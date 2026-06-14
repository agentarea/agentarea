#!/usr/bin/env python3
"""Run robust Agentarea agent scenarios against the dev API."""

from __future__ import annotations

import json
import os
import re
import time
import urllib.error
import urllib.request
import uuid
import zipfile
from io import BytesIO
from dataclasses import dataclass, field
from typing import Any


API = os.environ.get("API", "http://127.0.0.1:18000")
JWT = os.environ["JWT"]
MODEL_ID = os.environ["MODEL_ID"]


def request(method: str, path: str, payload: dict[str, Any] | None = None, timeout: int = 20) -> Any:
    data = None
    headers = {"Authorization": f"Bearer {JWT}"}
    if payload is not None:
        data = json.dumps(payload).encode()
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(API + path, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode()
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {body}") from e
    if not body:
        return None
    return json.loads(body)


def request_multipart(
    method: str,
    path: str,
    fields: dict[str, str],
    files: dict[str, tuple[str, bytes, str]],
    timeout: int = 30,
) -> Any:
    boundary = f"----agentarea-harness-{uuid.uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                str(value).encode(),
                b"\r\n",
            ]
        )
    for name, (filename, content, content_type) in files.items():
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="{name}"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                f"Content-Type: {content_type}\r\n\r\n".encode(),
                content,
                b"\r\n",
            ]
        )
    chunks.append(f"--{boundary}--\r\n".encode())
    body = b"".join(chunks)
    req = urllib.request.Request(
        API + path,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {JWT}",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            response_body = resp.read().decode()
    except urllib.error.HTTPError as e:
        response_body = e.read().decode(errors="replace")
        raise RuntimeError(f"{method} {path} -> HTTP {e.code}: {response_body}") from e
    return json.loads(response_body)


def post_task(agent_id: str, description: str) -> str:
    payload = json.dumps({"description": description}).encode()
    req = urllib.request.Request(
        f"{API}/v1/agents/{agent_id}/tasks/",
        data=payload,
        method="POST",
        headers={"Authorization": f"Bearer {JWT}", "Content-Type": "application/json"},
    )
    chunks: list[str] = []
    try:
        with urllib.request.urlopen(req, timeout=12) as resp:
            while True:
                line = resp.readline()
                if not line:
                    break
                text = line.decode(errors="replace")
                chunks.append(text)
                match = re.search(r'"task_id"\s*:\s*"([^"]+)"', "".join(chunks))
                if match:
                    return match.group(1)
    except TimeoutError:
        pass
    except urllib.error.URLError:
        pass
    body = "".join(chunks)
    match = re.search(r'"task_id"\s*:\s*"([^"]+)"', body) or re.search(
        r'"id"\s*:\s*"([^"]+)"', body
    )
    if not match:
        raise RuntimeError(f"Could not extract task id from response: {body[:1000]}")
    return match.group(1)


def create_agent(
    name: str,
    instruction: str,
    tools: list[dict[str, Any]] | None = None,
    skill_ids: list[str] | None = None,
) -> str:
    payload: dict[str, Any] = {
        "name": name,
        "description": f"Agent scenario {name}",
        "instruction": instruction,
        "model_id": MODEL_ID,
        "agent_type": "stateless",
        "planning": False,
        "tools": tools or [],
    }
    if skill_ids:
        payload["skill_ids"] = skill_ids
    agent = request("POST", "/v1/agents/", payload)
    return agent["id"]


def create_content_skill(name: str) -> str:
    content = f"""---
name: {name}
summary: Deterministic style rule skill for the Agentarea scenario harness.
---

When activated, answer the user with the exact marker requested in the task.
For this harness, the marker is `SCENARIO_PASS content_skill style=brief`.
Do not use scripts for this skill.
"""
    skill = request(
        "POST",
        "/v1/skills",
        {
            "name": name,
            "description": "Content-only skill fixture created by the scenario harness.",
            "content": content,
        },
    )
    return skill["id"]


def create_zip_skill(name: str) -> str:
    skill_md = f"""---
name: {name}
summary: Run sum_check.sh to prove package skills and sandbox scripts work.
---

Use `run_skill_script` with `sum_check.sh` to calculate the deterministic smoke sum.
The script prints `15`.
"""
    script = "#!/usr/bin/env sh\nset -eu\nprintf '%s\\n' $((2+5+8))\n"
    notes = "Fixture package for Agentarea scenario harness.\nExpected output: 15\n"
    buffer = BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("SKILL.md", skill_md)
        zf.writestr("sum_check.sh", script)
        zf.writestr("notes/example.txt", notes)
    skill = request_multipart(
        "POST",
        "/v1/skills/upload",
        {
            "name": name,
            "description": "Zip skill fixture created by the scenario harness.",
        },
        {"file": (f"{name}.zip", buffer.getvalue(), "application/zip")},
    )
    files = request("GET", f"/v1/skills/{skill['id']}/files")
    paths = {f["path"] for f in files.get("files", [])}
    expected = {"SKILL.md", "sum_check.sh", "notes/example.txt"}
    missing = expected - paths
    if missing:
        raise RuntimeError(f"Zip skill {name} missing files: {sorted(missing)}")
    return skill["id"]


def poll_events(agent_id: str, task_id: str, timeout_seconds: int = 180) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_count = -1
    while time.time() < deadline:
        events = request("GET", f"/v1/agents/{agent_id}/tasks/{task_id}/events", timeout=15)
        count = len(events.get("events", []))
        if count != last_count:
            print(f"  events={count}", flush=True)
            last_count = count
        for ev in events.get("events", []):
            if ev.get("event_type") in {"WorkflowCompleted", "WorkflowFailed"}:
                return events
        time.sleep(5)
    raise TimeoutError(f"Task {task_id} did not finish in {timeout_seconds}s")


def tool_events(events: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        e
        for e in events.get("events", [])
        if e.get("event_type") in {"ToolCallCompleted", "ToolCallFailed", "ToolCallStarted"}
    ]


def final_result(events: dict[str, Any]) -> str:
    for ev in events.get("events", []):
        if ev.get("event_type") == "WorkflowCompleted":
            meta = ev.get("metadata") or {}
            return str(meta.get("result") or meta.get("final_response") or "")
    return ""


def has_tool(events: dict[str, Any], tool_name: str, event_type: str = "ToolCallCompleted") -> bool:
    return any(
        e.get("event_type") == event_type and (e.get("metadata") or {}).get("tool_name") == tool_name
        for e in events.get("events", [])
    )


def no_tool_failures(events: dict[str, Any]) -> bool:
    return not any(e.get("event_type") == "ToolCallFailed" for e in events.get("events", []))


def create_postgres_mcp(name: str) -> str:
    payload = {
        "server": {
            "name": f"{name}-server",
            "description": "Postgres smoke MCP server",
            "cmd": [
                "npx",
                "-y",
                "@modelcontextprotocol/server-postgres",
                "postgresql://mcp:mcp@postgres-mcp-smoke:5432/mcp",
            ],
            "version": "1.0.0",
            "tags": ["postgres", "smoke"],
            "is_public": False,
            "env_schema": [],
        },
        "instance": {
            "name": name,
            "description": "Lazy Postgres MCP scenario instance",
            "json_spec": {
                "lazy_provisioning": True,
                "available_tools": [
                    {
                        "name": "query",
                        "description": "Run a read-only SQL query against the smoke PostgreSQL database.",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"sql": {"type": "string"}},
                            "required": ["sql"],
                        },
                    }
                ],
            },
        },
    }
    resp = request("POST", "/v1/mcp-server-instances/with-spec", payload, timeout=25)
    return resp["id"]


def cleanup_resource(path: str) -> None:
    try:
        request("DELETE", path, timeout=20)
    except Exception as exc:
        print(f"  cleanup warning for {path}: {exc}", flush=True)


@dataclass
class Scenario:
    name: str
    instruction: str
    prompt: str
    tools: list[dict[str, Any]] = field(default_factory=list)
    skill_ids: list[str] = field(default_factory=list)
    validate: Any = None


def main() -> int:
    suffix = str(int(time.time()))
    cleanup_paths: list[str] = []
    mcp_name = f"pg-agent-scenario-{suffix}"
    print(f"Creating lazy Postgres MCP: {mcp_name}", flush=True)
    mcp_id = create_postgres_mcp(mcp_name)
    cleanup_paths.append(f"/v1/mcp-server-instances/{mcp_id}")
    print(f"  mcp_id={mcp_id}", flush=True)

    content_skill_name = f"harness-content-skill-{suffix}"
    zip_skill_name = f"harness-zip-skill-{suffix}"
    print(f"Creating content skill: {content_skill_name}", flush=True)
    content_skill_id = create_content_skill(content_skill_name)
    cleanup_paths.append(f"/v1/skills/{content_skill_id}")
    print(f"  content_skill_id={content_skill_id}", flush=True)
    print(f"Creating zip skill: {zip_skill_name}", flush=True)
    zip_skill_id = create_zip_skill(zip_skill_name)
    cleanup_paths.append(f"/v1/skills/{zip_skill_id}")
    print(f"  zip_skill_id={zip_skill_id}", flush=True)

    base = "When done, call completion with a concise answer starting with SCENARIO_PASS."
    scenarios = [
        Scenario(
            name="llm_structured_answer",
            instruction=f"You answer exactly and briefly. {base}",
            prompt="Without tools, compute 2+5+8 and return 'SCENARIO_PASS llm sum=15'.",
            validate=lambda ev: "SCENARIO_PASS" in final_result(ev) and "15" in final_result(ev),
        ),
        Scenario(
            name="files_write_read_list",
            instruction=(
                f"Use tools exactly. Activate tool source 'agentarea/files'. After activation, "
                f"use the tool named 'files' with the appropriate action value. {base}"
            ),
            tools=[{"type": "code", "name": "agentarea/files"}],
            prompt=(
                "Call activate_tool_source for source_name 'agentarea/files'. Then call the files tool "
                "with action 'save_file', file_name 'scenario-files.txt', and contents "
                "'alpha=2\\nbeta=5\\ngamma=8'. Then call the files tool with action 'read_file' "
                "for that file. Then call the files tool with action 'list_files' and pattern '*.txt'. "
                "Finally complete with 'SCENARIO_PASS files read_sum=15'."
            ),
            validate=lambda ev: has_tool(ev, "files")
            and no_tool_failures(ev)
            and "SCENARIO_PASS" in final_result(ev),
        ),
        Scenario(
            name="web_fetch_health",
            instruction=f"Use web tools exactly and report observed status. {base}",
            tools=[{"type": "code", "name": "agentarea/web"}],
            prompt=(
                "Call activate_tool_source for source_name 'agentarea/web'. Then call the web tool "
                "with action 'fetch_webpage' for url 'http://agentarea-backend:8000/health'. Complete with "
                "'SCENARIO_PASS web status=<status from tool result>'."
            ),
            validate=lambda ev: has_tool(ev, "web")
            and no_tool_failures(ev)
            and "SCENARIO_PASS" in final_result(ev),
        ),
        Scenario(
            name="shell_sandbox_calc",
            instruction=f"Use shell exactly. {base}",
            tools=[{"type": "code", "name": "agentarea/shell"}],
            prompt=(
                "Call activate_tool_source for source_name 'agentarea/shell'. Then call the shell tool with "
                "command 'echo $((2+5+8))'. Complete with 'SCENARIO_PASS shell sum=15'."
            ),
            validate=lambda ev: has_tool(ev, "shell")
            and no_tool_failures(ev)
            and "15" in final_result(ev),
        ),
        Scenario(
            name="content_skill_activation",
            instruction=f"Use the content skill exactly. {base}",
            skill_ids=[content_skill_id],
            prompt=(
                f"Call activate_skill for skill_name '{content_skill_name}'. Then complete exactly with "
                "'SCENARIO_PASS content_skill style=brief'."
            ),
            validate=lambda ev: has_tool(ev, "activate_skill")
            and no_tool_failures(ev)
            and "SCENARIO_PASS content_skill" in final_result(ev),
        ),
        Scenario(
            name="zip_skill_script_sum",
            instruction=f"Use the package skill exactly. {base}",
            skill_ids=[zip_skill_id],
            prompt=(
                f"Call activate_skill for skill_name '{zip_skill_name}'. Then call run_skill_script "
                "with script_name 'sum_check.sh'. Complete with 'SCENARIO_PASS skill sum=<stdout>'."
            ),
            validate=lambda ev: has_tool(ev, "activate_skill")
            and has_tool(ev, "run_skill_script")
            and no_tool_failures(ev)
            and "15" in final_result(ev),
        ),
        Scenario(
            name="postgres_mcp_query",
            instruction=f"Use the Postgres MCP exactly. {base}",
            tools=[{"type": "mcp", "name": mcp_name}],
            prompt=(
                f"Call activate_tool_source for source_name '{mcp_name}'. Then call query exactly once "
                "with sql 'SELECT count(*) AS item_count, sum(qty) AS total_qty FROM codex_smoke_items;'. "
                "Complete with 'SCENARIO_PASS postgres item_count=<item_count> total_qty=<total_qty>'."
            ),
            validate=lambda ev: has_tool(ev, "query")
            and "SCENARIO_PASS" in final_result(ev)
            and "15" in final_result(ev),
        ),
        Scenario(
            name="file_shell_chain",
            instruction=f"Use shell and files exactly, chaining tool outputs. {base}",
            tools=[
                {"type": "code", "name": "agentarea/shell"},
                {"type": "code", "name": "agentarea/files"},
            ],
            prompt=(
                "Activate 'agentarea/shell' and 'agentarea/files'. Call the shell tool with command "
                "'printf agentarea | wc -c'. Then call the files tool with action 'save_file' to save "
                "the stripped output to file_name 'chain.txt'. Then call the files tool with action "
                "'read_file' for 'chain.txt'. Complete with 'SCENARIO_PASS chain chars=9'."
            ),
            validate=lambda ev: has_tool(ev, "shell")
            and has_tool(ev, "files")
            and no_tool_failures(ev)
            and "SCENARIO_PASS" in final_result(ev),
        ),
        Scenario(
            name="web_error_handling",
            instruction=(
                "Use web tools. If the fetch returns an Error, do not retry the same URL; "
                f"complete with a clear handled-error answer. {base}"
            ),
            tools=[{"type": "code", "name": "agentarea/web"}],
            prompt=(
                "Call activate_tool_source for source_name 'agentarea/web'. Then call the web tool "
                "with action 'fetch_webpage' for url 'https://nonexistent.agentarea.invalid/'. "
                "If it fails, complete with "
                "'SCENARIO_PASS handled_web_error'."
            ),
            validate=lambda ev: has_tool(ev, "web") and "SCENARIO_PASS" in final_result(ev),
        ),
    ]

    results = []
    for scenario in scenarios:
        print(f"\n=== {scenario.name} ===", flush=True)
        agent_id = create_agent(
            f"{scenario.name}-{suffix}",
            scenario.instruction,
            scenario.tools,
            scenario.skill_ids,
        )
        print(f"  agent_id={agent_id}", flush=True)
        task_id = post_task(agent_id, scenario.prompt)
        print(f"  task_id={task_id}", flush=True)
        try:
            events = poll_events(agent_id, task_id)
            ok = bool(scenario.validate(events)) if scenario.validate else True
            result = final_result(events)
            tools_seen = [
                f"{e.get('event_type')}:{(e.get('metadata') or {}).get('tool_name')}"
                for e in tool_events(events)
            ]
            status = "PASS" if ok else "FAIL"
            print(f"  {status}: {result[:300]}", flush=True)
            results.append(
                {
                    "name": scenario.name,
                    "status": status,
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "result": result,
                    "tools": tools_seen,
                }
            )
        except Exception as e:
            print(f"  ERROR: {e}", flush=True)
            results.append(
                {
                    "name": scenario.name,
                    "status": "ERROR",
                    "agent_id": agent_id,
                    "task_id": task_id,
                    "result": str(e),
                    "tools": [],
                }
            )

    print("\n=== SUMMARY_JSON ===")
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print("\n=== CLEANUP ===", flush=True)
    for path in reversed(cleanup_paths):
        print(f"  delete {path}", flush=True)
        cleanup_resource(path)
    return 0 if all(r["status"] == "PASS" for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
