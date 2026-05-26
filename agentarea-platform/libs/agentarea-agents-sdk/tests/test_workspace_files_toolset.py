import json

import pytest

from agentarea_agents_sdk.tools.code_tools_loader import create_code_tool_instance
from agentarea_agents_sdk.tools.file_toolset import InMemoryStorage


@pytest.mark.asyncio
async def test_workspace_files_toolset_runs_without_api_package_context():
    storage = InMemoryStorage()
    await storage.put("workspace-1", "shared/report.html", b"<html>ok</html>", "text/html")

    toolset = create_code_tool_instance(
        "agentarea/workspace_files",
        extra_kwargs={
            "storage": storage,
            "workspace_id": "workspace-1",
            "base_prefix": "shared",
        },
    )

    assert toolset is not None
    assert toolset.__class__.__module__.startswith("agentarea_agents_sdk.")

    listed = json.loads(await toolset.list())
    assert listed == [
        {"path": "report.html", "size": 15, "content_type": "text/html"},
    ]

    url = json.loads(await toolset.get_url("report.html"))
    assert url["url"] == "/v1/files/download/shared/report.html"

    deleted = json.loads(await toolset.delete("report.html"))
    assert deleted == {"deleted": True, "path": "report.html"}
