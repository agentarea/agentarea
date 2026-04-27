from __future__ import annotations

import io

import httpx
import pytest
import yaml

from tests.e2e.api.conftest import create_agent


@pytest.mark.integration
def test_workspace_import_yaml_roundtrip(alice_client: httpx.Client, llm_model: str) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="import-test-agent",
        instruction="ok.",
    )

    export_resp = alice_client.get("/v1/workspace/export")
    assert export_resp.status_code == 200, export_resp.text[:200]
    original_yaml = export_resp.text
    original = yaml.safe_load(original_yaml)
    assert original.get("agents"), f"expected agents in export, got {original}"

    import_resp = alice_client.post(
        "/v1/workspace/import",
        json={
            "yaml_content": original_yaml,
            "override_existing": True,
        },
    )
    if import_resp.status_code == 400 and "API key is required" in import_resp.text:
        pytest.skip("Import requires real API keys in exported provider configs")
    assert import_resp.status_code == 200, import_resp.text[:200]
    result = import_resp.json()
    assert result.get("success") is True or result.get("imported_count", 0) > 0, (
        f"import failed: {result}"
    )


@pytest.mark.integration
def test_workspace_import_file_roundtrip(alice_client: httpx.Client, llm_model: str) -> None:
    agent_id = create_agent(
        alice_client,
        llm_model,
        name="import-file-agent",
        instruction="ok.",
    )

    export_resp = alice_client.get("/v1/workspace/export")
    export_resp.raise_for_status()

    file_content = io.BytesIO(export_resp.content)
    import_resp = alice_client.post(
        "/v1/workspace/import/file?override_existing=true",
        files={"file": ("workspace.yaml", file_content, "text/yaml")},
    )
    if import_resp.status_code == 400 and "API key is required" in import_resp.text:
        pytest.skip("Import requires real API keys in exported provider configs")
    assert import_resp.status_code == 200, import_resp.text[:200]
    result = import_resp.json()
    assert result.get("success") is True or result.get("imported_count", 0) > 0


@pytest.mark.integration
def test_workspace_import_invalid_yaml_rejected(alice_client: httpx.Client) -> None:
    resp = alice_client.post(
        "/v1/workspace/import",
        json={"yaml_content": "not: valid: yaml: [["},
    )
    assert resp.status_code in (400, 422), (
        f"Expected 400/422 for invalid YAML, got {resp.status_code}: {resp.text[:200]}"
    )


@pytest.mark.integration
def test_workspace_import_is_workspace_scoped(
    alice_client: httpx.Client, bob_client: httpx.Client, llm_model: str
) -> None:
    alice_client.post(
        "/v1/projects/", json={"name": "alice-import-project"}
    ).raise_for_status()

    export_resp = alice_client.get("/v1/workspace/export").raise_for_status()

    bob_import = bob_client.post(
        "/v1/workspace/import",
        json={"yaml_content": export_resp.text, "override_existing": True},
    )
    bob_projects = bob_client.get("/v1/projects/").raise_for_status().json()
    bob_names = {p["name"] for p in bob_projects}
    assert "alice-import-project" not in bob_names, (
        "CRITICAL: Alice's project leaked into Bob's workspace via import"
    )
