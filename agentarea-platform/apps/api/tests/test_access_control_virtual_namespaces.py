"""Tests for virtual graph namespaces in the access-control API."""

import pytest
from agentarea_api.api.v1.access_control import (
    _assert_object_in_workspace,
    _assert_relationship_mutable_namespace,
)
from agentarea_common.auth.context import UserContext
from fastapi import HTTPException


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", ["Tool", "ToolResource"])
async def test_virtual_namespaces_do_not_require_db_backed_uuid(namespace):
    context = UserContext(user_id="u1", workspace_id="ws1")
    suffix = "~args~abc" if namespace == "ToolResource" else ""
    await _assert_object_in_workspace(namespace, f"ws1/github.create_issue{suffix}", context, None)


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", ["Tool", "ToolResource"])
async def test_virtual_namespaces_reject_other_workspace(namespace):
    context = UserContext(user_id="u1", workspace_id="ws1")
    suffix = "~args~abc" if namespace == "ToolResource" else ""
    with pytest.raises(HTTPException) as exc:
        await _assert_object_in_workspace(namespace, f"ws2/github.create_issue{suffix}", context, None)

    assert exc.value.status_code == 403


@pytest.mark.asyncio
async def test_unknown_namespace_still_rejected():
    with pytest.raises(HTTPException) as exc:
        await _assert_object_in_workspace("Unknown", "x", None, None)

    assert exc.value.status_code == 422


@pytest.mark.parametrize("namespace", ["Tool", "ToolResource"])
def test_virtual_namespaces_are_not_mutable_through_generic_relationship_api(namespace):
    with pytest.raises(HTTPException) as exc:
        _assert_relationship_mutable_namespace(namespace)

    assert exc.value.status_code == 422
    assert "tool-access" in exc.value.detail
