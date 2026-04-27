"""Model-spec HTTP API end-to-end tests."""

from __future__ import annotations

import uuid

import httpx
import pytest


def _payload(provider_spec_id: str, model_name: str | None = None) -> dict:
    name = model_name or f"e2e-model-{uuid.uuid4().hex[:10]}"
    return {
        "provider_spec_id": provider_spec_id,
        "model_name": name,
        "display_name": f"E2E {name}",
        "description": "created by api e2e",
        "context_window": 8192,
        "default_context_strategy": "static",
        "is_active": True,
    }


@pytest.mark.integration
def test_model_spec_lifecycle(
    alice_client: httpx.Client, llm_provider_spec_id: str
) -> None:
    data = _payload(llm_provider_spec_id)

    created = alice_client.post("/v1/model-specs/", json=data)
    assert created.status_code == 200, created.text[:200]
    spec = created.json()
    spec_id = spec["id"]
    assert spec["model_name"] == data["model_name"]
    assert spec["context_window"] == 8192

    duplicate = alice_client.post("/v1/model-specs/", json=data)
    assert duplicate.status_code == 409

    fetched = alice_client.get(f"/v1/model-specs/{spec_id}")
    assert fetched.status_code == 200
    assert fetched.json()["id"] == spec_id

    by_provider = alice_client.get(f"/v1/model-specs/by-provider/{llm_provider_spec_id}")
    assert by_provider.status_code == 200
    assert any(item["id"] == spec_id for item in by_provider.json())

    by_name = alice_client.get(
        f"/v1/model-specs/by-provider/{llm_provider_spec_id}/{data['model_name']}"
    )
    assert by_name.status_code == 200
    assert by_name.json()["id"] == spec_id

    patched = alice_client.patch(
        f"/v1/model-specs/{spec_id}",
        json={"display_name": "E2E patched", "context_window": 16384},
    )
    assert patched.status_code == 200
    assert patched.json()["display_name"] == "E2E patched"
    assert patched.json()["context_window"] == 16384

    upserted = alice_client.post(
        "/v1/model-specs/upsert",
        json={**data, "display_name": "E2E upserted", "context_window": 32768},
    )
    assert upserted.status_code == 200
    assert upserted.json()["id"] == spec_id
    assert upserted.json()["display_name"] == "E2E upserted"
    assert upserted.json()["context_window"] == 32768

    deleted = alice_client.delete(f"/v1/model-specs/{spec_id}")
    assert deleted.status_code == 200

    gone = alice_client.get(f"/v1/model-specs/{spec_id}")
    assert gone.status_code == 404


@pytest.mark.integration
def test_model_specs_are_workspace_scoped(
    alice_client: httpx.Client,
    bob_client: httpx.Client,
    llm_provider_spec_id: str,
) -> None:
    created = alice_client.post(
        "/v1/model-specs/", json=_payload(llm_provider_spec_id)
    )
    assert created.status_code == 200, created.text[:200]
    spec_id = created.json()["id"]

    bob_get = bob_client.get(f"/v1/model-specs/{spec_id}")
    assert bob_get.status_code == 404

    bob_list = bob_client.get("/v1/model-specs/")
    assert bob_list.status_code == 200
    assert all(item["id"] != spec_id for item in bob_list.json())

