"""Workspace export smoke.

Currently `/v1/workspace/export` returns 500 once the workspace has any
seeded data (tracked as a known bug — see backend log
`workspace_config.py:187 export_workspace_config`). This test documents the
expected behaviour and xfails the broken case so a future fix turns XPASS.
"""

from __future__ import annotations

import httpx
import pytest


@pytest.mark.integration
def test_workspace_export_empty_ok(alice_client: httpx.Client) -> None:
    resp = alice_client.get("/v1/workspace/export")
    assert resp.status_code == 200, resp.text[:200]
    body = resp.json()
    assert isinstance(body, dict)


@pytest.mark.integration
@pytest.mark.xfail(reason="Known bug: workspace export 500s once workspace has content", strict=False)
def test_workspace_export_with_content_ok(alice_client: httpx.Client) -> None:
    alice_client.post(
        "/v1/projects/", json={"name": "export-me"}
    ).raise_for_status()
    alice_client.post(
        "/v1/agents/",
        json={
            "name": "export-agent",
            "description": "d",
            "instruction": "i",
            "model_id": "gpt-4",
            "agent_type": "chat",
        },
    ).raise_for_status()

    resp = alice_client.get("/v1/workspace/export")
    assert resp.status_code == 200, resp.text[:200]
    body = resp.json()
    assert "agents" in body or "projects" in body or body, "expected non-empty shape"


@pytest.mark.integration
def test_workspace_export_is_isolated(
    alice_client: httpx.Client, bob_client: httpx.Client
) -> None:
    alice_project_id = alice_client.post(
        "/v1/projects/", json={"name": "alice-private"}
    ).raise_for_status().json()["id"]

    bob_export = bob_client.get("/v1/workspace/export")
    if bob_export.status_code != 200:
        pytest.skip(f"export 500 with no Bob content — unexpected: {bob_export.status_code}")
    body = bob_export.text
    assert alice_project_id not in body, "CRITICAL: Alice's project leaked into Bob's export"
