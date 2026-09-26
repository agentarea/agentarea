"""Cross-workspace isolation, parametrized across resource types.

For each resource we assert:
  1. list for Alice and Bob don't overlap
  2. GET-by-id of Alice's resource by Bob returns 404
  3. DELETE of Alice's resource by Bob returns 403/404 AND Alice's resource survives
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

import pytest

from .conftest import WorkspaceClient


@dataclass(frozen=True)
class ResourceSpec:
    label: str
    collection: str  # POST + GET list path, relative to the workspace
    item_template: str  # e.g. "/skills/{id}"
    payload: dict


RESOURCES = [
    ResourceSpec(
        label="projects",
        collection="/projects/",
        item_template="/projects/{id}",
        payload={"name": "iso-project", "description": "isolation test"},
    ),
    ResourceSpec(
        label="skills",
        collection="/skills",
        item_template="/skills/{id}",
        payload={"name": "iso-skill", "description": "isolation test", "content": "# hello"},
    ),
    ResourceSpec(
        label="registries",
        collection="/registries/",
        item_template="/registries/{id}",
        payload={
            "name": "iso-registry",
            "registry_type": "mcp_servers",
            "source_type": "url",
            "source_url": f"https://example.com/nonexistent-{uuid.uuid4().hex[:8]}.json",
            "sync_mode": "manual",
        },
    ),
    ResourceSpec(
        label="openapi-connections",
        collection="/openapi-connections/",
        item_template="/openapi-connections/{id}",
        payload={"name": "iso-openapi", "base_url": "https://example.com"},
    ),
    ResourceSpec(
        label="api-keys",
        collection="/api-keys/",
        item_template="/api-keys/{id}",
        payload={"name": "iso-api-key"},
    ),
    ResourceSpec(
        label="agents",
        collection="/agents/",
        item_template="/agents/{id}",
        payload={
            "name": "iso-agent",
            "description": "isolation test",
            "instruction": "behave",
            "agent_type": "stateless",
        },
    ),
    ResourceSpec(
        label="mcp-server-instances",
        collection="/mcp-server-instances/",
        item_template="/mcp-server-instances/{id}",
        payload={
            "name": "iso-mcp",
            "json_spec": {
                "name": "iso-mcp",
                "version": "1.0.0",
                "image": "alpine:latest",
                "port": 8080,
                "packages": [],
            },
        },
    ),
]


@pytest.mark.integration
@pytest.mark.parametrize("spec", RESOURCES, ids=lambda s: s.label)
def test_list_scoped_per_user(
    spec: ResourceSpec, alice_client: WorkspaceClient, bob_client: WorkspaceClient
) -> None:
    alice_resp = alice_client.post(f"{alice_client.ws}{spec.collection}", json=spec.payload)
    if alice_resp.status_code >= 400:
        pytest.skip(f"create failed for {spec.label}: {alice_resp.status_code} {alice_resp.text[:200]}")
    alice_id = alice_resp.json()["id"]

    bob_resp = bob_client.post(f"{bob_client.ws}{spec.collection}", json=spec.payload)
    assert bob_resp.status_code < 300, f"Bob's create failed: {bob_resp.text[:200]}"
    bob_id = bob_resp.json()["id"]

    alice_items = alice_client.get(f"{alice_client.ws}{spec.collection}").json()
    bob_items = bob_client.get(f"{bob_client.ws}{spec.collection}").json()
    alice_items = alice_items if isinstance(alice_items, list) else alice_items.get("items", [])
    bob_items = bob_items if isinstance(bob_items, list) else bob_items.get("items", [])

    alice_ids = {x["id"] for x in alice_items}
    bob_ids = {x["id"] for x in bob_items}

    assert alice_id in alice_ids
    assert bob_id in bob_ids
    assert alice_id not in bob_ids, f"{spec.label}: Bob can see Alice's item"
    assert bob_id not in alice_ids, f"{spec.label}: Alice can see Bob's item"


@pytest.mark.integration
@pytest.mark.parametrize("spec", RESOURCES, ids=lambda s: s.label)
def test_cross_workspace_get_returns_404(
    spec: ResourceSpec, alice_client: WorkspaceClient, bob_client: WorkspaceClient
) -> None:
    alice_resp = alice_client.post(f"{alice_client.ws}{spec.collection}", json=spec.payload)
    if alice_resp.status_code >= 400:
        pytest.skip(f"create failed for {spec.label}: {alice_resp.status_code}")
    alice_id = alice_resp.json()["id"]

    bob_view = bob_client.get(f"{bob_client.ws}{spec.item_template.format(id=alice_id)}")
    assert bob_view.status_code == 404, (
        f"{spec.label}: Bob should not see Alice's item, got {bob_view.status_code}: {bob_view.text[:200]}"
    )


@pytest.mark.integration
@pytest.mark.parametrize("spec", RESOURCES, ids=lambda s: s.label)
def test_cross_workspace_delete_is_blocked(
    spec: ResourceSpec, alice_client: WorkspaceClient, bob_client: WorkspaceClient
) -> None:
    alice_resp = alice_client.post(f"{alice_client.ws}{spec.collection}", json=spec.payload)
    if alice_resp.status_code >= 400:
        pytest.skip(f"create failed for {spec.label}: {alice_resp.status_code}")
    alice_id = alice_resp.json()["id"]

    del_resp = bob_client.delete(f"{bob_client.ws}{spec.item_template.format(id=alice_id)}")
    assert del_resp.status_code in (403, 404), (
        f"{spec.label}: Bob's delete returned {del_resp.status_code}: {del_resp.text[:200]}"
    )

    survives = alice_client.get(f"{alice_client.ws}{spec.item_template.format(id=alice_id)}")
    assert survives.status_code == 200, (
        f"{spec.label}: Alice's item must survive Bob's delete attempt"
    )
