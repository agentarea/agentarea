"""Tests for namespace handling in the access-control API."""

import pytest
from agentarea_api.api.v1.access_control import _assert_object_in_workspace
from fastapi import HTTPException


@pytest.mark.asyncio
async def test_unknown_namespace_is_rejected():
    with pytest.raises(HTTPException) as exc:
        await _assert_object_in_workspace("Unknown", "x", None, None)

    assert exc.value.status_code == 422
