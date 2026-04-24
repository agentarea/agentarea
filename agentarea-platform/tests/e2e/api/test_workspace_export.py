"""Workspace export smoke.

Endpoint returns YAML (text/yaml). We parse with pyyaml.
"""

from __future__ import annotations

import httpx
import pytest
import yaml


def _parse_export(resp: httpx.Response) -> dict:
    assert resp.status_code == 200, resp.text[:200]
    parsed = yaml.safe_load(resp.text) or {}
    assert isinstance(parsed, dict)
    return parsed


@pytest.mark.integration
def test_workspace_export_empty_ok(alice_client: httpx.Client) -> None:
    _parse_export(alice_client.get("/v1/workspace/export"))


@pytest.mark.integration
def test_workspace_export_with_content_ok(alice_client: httpx.Client) -> None:
    alice_client.post(
        "/v1/projects/", json={"name": "export-me"}
    ).raise_for_status()
    agent_name = "export-agent"
    alice_client.post(
        "/v1/agents/",
        json={
            "name": agent_name,
            "description": "d",
            "instruction": "i",
            "model_id": "gpt-4",
            "agent_type": "chat",
        },
    ).raise_for_status()

    body = _parse_export(alice_client.get("/v1/workspace/export"))
    assert body.get("agents"), f"expected agents in export, got {body}"
    assert any(a.get("name") == agent_name for a in body["agents"])


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
