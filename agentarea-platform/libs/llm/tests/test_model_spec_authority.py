"""A model spec's price is what every budget in the workspace is computed from.

``POST/PATCH/DELETE /v1/model-specs`` and both discovery routes wrote specs as
any member, so a member could zero the per-token price of a model and no spend
cap would ever trip. A price of 0 is legitimate (free or local models); what is
guarded is who may set it.
"""

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
from agentarea_common.auth.authorization import AuthorizationService
from agentarea_common.auth.context import UserContext
from agentarea_common.auth.workspace_authorization import WorkspaceScopedAuthorizationService
from agentarea_common.di.container import get_container
from agentarea_llm.application.model_spec_service import ModelSpecService
from fastapi import HTTPException

WORKSPACE = "ws-acme"
MEMBER = UserContext(user_id="user-member", workspace_id=WORKSPACE, admin_workspaces=[])
OWNER = UserContext(user_id="user-owner", workspace_id=WORKSPACE, admin_workspaces=[WORKSPACE])
FREE_MODEL = {
    "provider_spec_id": str(uuid4()),
    "model_name": "llama3",
    "display_name": "Llama 3",
    "context_window": 8192,
    "input_cost_per_token": 0.0,
    "output_cost_per_token": 0.0,
}


@pytest.fixture(autouse=True)
def _authorization():
    container = get_container()
    saved = dict(container._singletons)
    container.register_singleton(AuthorizationService, WorkspaceScopedAuthorizationService())
    yield
    container._singletons.clear()
    container._singletons.update(saved)


def _service(user_context: UserContext) -> tuple[ModelSpecService, MagicMock]:
    repo = MagicMock()
    repo.user_context = user_context
    for method in ("create", "update", "delete", "upsert_by_provider_and_model_kwargs"):
        setattr(repo, method, AsyncMock())
    return ModelSpecService(repo), repo


WRITES = {
    "create": lambda s: s.create(**FREE_MODEL),
    "update": lambda s: s.update(uuid4(), input_cost_per_token=0.0),
    "delete": lambda s: s.delete(uuid4()),
    "upsert": lambda s: s.upsert(**FREE_MODEL),
}


@pytest.mark.asyncio
@pytest.mark.parametrize("write", WRITES.values(), ids=WRITES.keys())
async def test_a_member_cannot_write_a_model_spec(write) -> None:
    service, repo = _service(MEMBER)

    with pytest.raises(HTTPException) as refused:
        await write(service)

    assert refused.value.status_code == 403
    for method in ("create", "update", "delete", "upsert_by_provider_and_model_kwargs"):
        getattr(repo, method).assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("write", WRITES.values(), ids=WRITES.keys())
async def test_an_admin_may_set_any_price_including_zero(write) -> None:
    service, repo = _service(OWNER)

    await write(service)

    assert any(
        getattr(repo, m).await_count
        for m in ("create", "update", "delete", "upsert_by_provider_and_model_kwargs")
    )
