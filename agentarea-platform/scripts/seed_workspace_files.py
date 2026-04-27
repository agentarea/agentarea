"""Seed a workspace with a handful of demo files for the /files UI.

Usage::

    cd agentarea-platform
    uv run python scripts/seed_workspace_files.py <workspace_id>

Drops the files directly through ``ArtifactService``, which is the same
path agents use — so the result is byte-identical to what an agent run
would have produced.
"""

from __future__ import annotations

import asyncio
import json
import sys

from agentarea_common.artifacts import ArtifactService

DEMO_FILES: list[tuple[str, bytes, str]] = [
    (
        "tasks/demo-task/output.log",
        b"INFO  starting agent run\n"
        b"INFO  thinking...\n"
        b"INFO  done.\n",
        "text/plain",
    ),
    (
        "tasks/demo-task/result.json",
        json.dumps({"status": "ok", "iterations": 3}, indent=2).encode(),
        "application/json",
    ),
]


async def main(workspace_id: str) -> None:
    svc = ArtifactService()
    print(f"seeding workspace={workspace_id} bucket={svc.bucket}")
    for path, body, content_type in DEMO_FILES:
        await svc.put(workspace_id, path, body, content_type=content_type)
        print(f"  put workspaces/{workspace_id}/{path} ({len(body)} bytes)")
    print("done.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__)
        sys.exit(2)
    asyncio.run(main(sys.argv[1]))
