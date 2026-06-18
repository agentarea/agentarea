"""API tests for ``POST /v1/model-specs/``.

Covers the two duplicate paths:

  * pre-check: ``get_by_provider_and_model`` returns an existing row → 409.
  * race: pre-check passes but ``create`` trips the unique constraint and
    raises ``IntegrityError`` → 409 (no longer 500).
"""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_api.api.deps.services import get_model_spec_repository
from agentarea_api.api.v1.model_specs import router
from agentarea_common.auth import UserContext, get_user_context
from agentarea_common.testing.flows import MainFlow
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError


def _spec(provider_spec_id, model_name="gpt-4"):
    spec = MagicMock()
    spec.id = uuid4()
    spec.provider_spec_id = provider_spec_id
    spec.model_name = model_name
    spec.display_name = "GPT-4"
    spec.description = None
    spec.context_window = 8192
    spec.max_output_tokens = 4096
    spec.input_cost_per_token = 0.0
    spec.output_cost_per_token = 0.0
    spec.supports_function_calling = True
    spec.supports_vision = False
    spec.supports_reasoning = False
    spec.default_context_strategy = None
    spec.is_active = True
    spec.created_at = datetime.now(UTC)
    spec.updated_at = datetime.now(UTC)
    spec.provider_spec = None
    return spec


@pytest.fixture
def repo():
    return AsyncMock()


@pytest.fixture
def client(repo):
    app = FastAPI()
    app.include_router(router, prefix="/v1")
    app.dependency_overrides[get_model_spec_repository] = lambda: repo
    app.dependency_overrides[get_user_context] = lambda: UserContext(
        user_id="u-1", workspace_id="ws-1"
    )
    return TestClient(app)


def _payload(provider_spec_id):
    return {
        "provider_spec_id": str(provider_spec_id),
        "model_name": "gpt-4",
        "display_name": "GPT-4",
        "context_window": 8192,
    }


@pytest.mark.flow(MainFlow.PROVIDER_MODEL_CONFIG)
def test_create_returns_200_when_no_duplicate(client, repo):
    provider_spec_id = uuid4()
    spec = _spec(provider_spec_id)
    repo.get_by_provider_and_model.return_value = None
    repo.create.return_value = spec
    repo.get_with_relations.return_value = spec

    resp = client.post("/v1/model-specs/", json=_payload(provider_spec_id))

    assert resp.status_code == 200
    assert resp.json()["model_name"] == "gpt-4"
    repo.create.assert_called_once()


def test_create_returns_409_when_pre_check_finds_duplicate(client, repo):
    provider_spec_id = uuid4()
    repo.get_by_provider_and_model.return_value = _spec(provider_spec_id)

    resp = client.post("/v1/model-specs/", json=_payload(provider_spec_id))

    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]
    repo.create.assert_not_called()


def test_create_returns_409_on_race_against_unique_constraint(client, repo):
    provider_spec_id = uuid4()
    repo.get_by_provider_and_model.return_value = None
    repo.create.side_effect = IntegrityError(
        "INSERT", params=None, orig=Exception("unique violation")
    )

    resp = client.post("/v1/model-specs/", json=_payload(provider_spec_id))

    assert resp.status_code == 409
    assert "already exists" in resp.json()["detail"]
