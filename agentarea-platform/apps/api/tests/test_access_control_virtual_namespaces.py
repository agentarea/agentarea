"""Tests for virtual graph namespaces in the access-control API."""

import pytest
from agentarea_api.api.v1.access_control import _assert_object_in_workspace
from fastapi import HTTPException


@pytest.mark.asyncio
@pytest.mark.parametrize("namespace", ["Tool", "ToolResource"])
async def test_virtual_namespaces_do_not_require_db_backed_uuid(namespace):
    await _assert_object_in_workspace(namespace, "github.create_issue~args~abc", None, None)


@pytest.mark.asyncio
async def test_unknown_namespace_still_rejected():
    with pytest.raises(HTTPException) as exc:
        await _assert_object_in_workspace("Unknown", "x", None, None)

    assert exc.value.status_code == 422
