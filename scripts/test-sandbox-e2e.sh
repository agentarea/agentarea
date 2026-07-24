#!/usr/bin/env bash
# End-to-end proof for the canonical refs-only task workspace transport.
set -euo pipefail

cd "$(dirname "$0")/.."

step() { printf '\n\033[1;34m▸ %s\033[0m\n' "$1"; }
ok() { printf '\033[32m✓ %s\033[0m\n' "$1"; }

step "Running manifest hydration/writeback through the live compose stack"
docker compose -f docker-compose.dev.yaml exec -T app python - <<'PY'
import asyncio
import json
import os
import time
import uuid

import httpx
import redis
from agentarea_common.artifacts import WorkspaceRepository


async def main() -> None:
    workspace_id = f"e2e-{uuid.uuid4().hex[:12]}"
    task_id = f"task-{uuid.uuid4().hex[:12]}"
    canary = f"refs-only-canary-{uuid.uuid4().hex}".encode()
    heredoc_canary = f"heredoc-body-canary-{uuid.uuid4().hex}".encode()
    repository = WorkspaceRepository()
    await repository.put(workspace_id, task_id, "inputs/seed.txt", canary)
    command_path = f".agentarea/commands/{uuid.uuid4().hex}.sh"
    command = (
        b"mkdir -p reports/2026\n"
        b"cat inputs/seed.txt\n"
        b"cp inputs/seed.txt reports/2026/q3.txt\n"
        b"printf '\\nverified' >> reports/2026/q3.txt\n"
        b"cat > reports/2026/heredoc.txt <<'AGENTAREA_CANARY'\n"
        + heredoc_canary
        + b"\nAGENTAREA_CANARY\n"
    )
    await repository.put(
        workspace_id,
        task_id,
        command_path,
        command,
        content_type="text/x-shellscript",
        provenance={"source": "e2e_shell_command"},
    )
    manifest_ref = await repository.checkout_for_execution(
        workspace_id,
        task_id,
        owner=f"e2e-{uuid.uuid4().hex}",
    )

    payload = {
        "workflow_id": f"task-{task_id}",
        "workspace_id": workspace_id,
        "task_id": task_id,
        "runtime": {"provider": "agentarea-k8s", "package_install": "allowed"},
        "workspace_manifest_ref": manifest_ref.to_dict(),
        "command": {
            "command_path": command_path,
            "timeout_seconds": 60,
            "workflow_id": f"task-{task_id}",
        },
    }

    async with httpx.AsyncClient(base_url="http://mcp-manager:80", timeout=90) as client:
        response = await client.post("/sandbox/executions", json=payload)
        response.raise_for_status()
        record = response.json()
        execution_id = record["id"]
        deadline = time.monotonic() + 90
        while record["status"] not in {"completed", "failed", "cancelled"}:
            if time.monotonic() >= deadline:
                raise AssertionError(f"execution {execution_id} did not finish: {record}")
            await asyncio.sleep(0.5)
            response = await client.get(f"/sandbox/executions/{execution_id}")
            response.raise_for_status()
            record = response.json()

    if record["status"] != "completed" or record.get("result", {}).get("exit_code") != 0:
        raise AssertionError(f"sandbox execution failed: {record}")
    expected = canary + b"\nverified"
    actual, _ = await repository.get(workspace_id, task_id, "reports/2026/q3.txt")
    if actual != expected:
        raise AssertionError(f"writeback mismatch: {actual!r}")
    heredoc_actual, _ = await repository.get(
        workspace_id, task_id, "reports/2026/heredoc.txt"
    )
    if heredoc_actual != heredoc_canary + b"\n":
        raise AssertionError(f"heredoc writeback mismatch: {heredoc_actual!r}")
    stdout_ref = record.get("result", {}).get("stdout_ref", {})
    stdout, _ = await repository.get_object_ref(workspace_id, task_id, stdout_ref)
    if stdout.rstrip(b"\n") != canary:
        raise AssertionError(f"stdout ref mismatch: {stdout!r}")

    redis_client = redis.Redis.from_url(os.environ["REDIS_URL"])
    samples: list[bytes] = []
    record_bytes = redis_client.get(f"agentarea:sandbox:execution:{execution_id}")
    if record_bytes:
        samples.append(record_bytes)
    for stream in (
        "agentarea.sandbox.execution.requests",
        "agentarea.sandbox.execution.events",
    ):
        for _message_id, fields in redis_client.xrange(stream):
            wire = json.dumps(
                {
                    key.decode() if isinstance(key, bytes) else str(key):
                    value.decode(errors="replace") if isinstance(value, bytes) else str(value)
                    for key, value in fields.items()
                },
                sort_keys=True,
            ).encode()
            if execution_id.encode() in wire:
                samples.append(wire)
    combined = b"\n".join(samples)
    forbidden = [
        canary,
        heredoc_canary,
        command,
        b"content_base64",
        b"input_files",
        b"script_content",
        b"X-Amz-Signature",
        os.environ.get("AWS_ACCESS_KEY_ID", "").encode(),
        os.environ.get("AWS_SECRET_ACCESS_KEY", "").encode(),
    ]
    for value in forbidden:
        if value and value in combined:
            raise AssertionError("Redis contains a forbidden workspace payload or credential")
    print(
        json.dumps(
            {
                "execution_id": execution_id,
                "generation": record["workspace_manifest_ref"]["generation"],
                "redis_sample_bytes": len(combined),
                "output_bytes": len(actual),
            },
            sort_keys=True,
        )
    )


asyncio.run(main())
PY

ok "S3 hydration/writeback succeeded and execution-specific Redis payloads are refs-only"
