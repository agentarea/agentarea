"""``json_spec.storage`` takes only the value the MCP manager starts an app with.

The manager refuses to start an instance whose ``storage`` is anything but
``{"enabled": true}``; refusing it on write keeps that failure out of the first
tool call.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from agentarea_mcp.schemas.dto import (
    MCPServerCreate,
    MCPServerInstanceCreate,
    MCPServerInstanceUpdate,
    MCPServerUpdate,
)
from pydantic import ValidationError

BAD_STORAGE = [
    {"enabled": False},
    {"enabled": 1},
    {"enabled": "true"},
    {"enabled": True, "quota": 10},
    {},
    True,
    "s3",
]


@pytest.mark.parametrize("storage", BAD_STORAGE)
def test_every_other_storage_value_is_refused(storage) -> None:
    spec = {"type": "docker", "image": "ghcr.io/acme/app:1", "storage": storage}
    with pytest.raises(ValidationError, match="storage"):
        MCPServerCreate(name="s", description="d", version="1", json_spec=spec)
    with pytest.raises(ValidationError, match="storage"):
        MCPServerUpdate(json_spec=spec)
    with pytest.raises(ValidationError, match="storage"):
        MCPServerInstanceCreate(name="i", server_spec_id=uuid4(), json_spec=spec)
    with pytest.raises(ValidationError, match="storage"):
        MCPServerInstanceUpdate(json_spec={"storage": storage})


def test_the_opt_in_is_accepted_and_stored_as_sent() -> None:
    spec = {"type": "docker", "image": "ghcr.io/acme/app:1", "storage": {"enabled": True}}

    assert MCPServerUpdate(json_spec=spec).json_spec == spec
    assert MCPServerCreate(name="s", description="d", version="1", json_spec=spec).json_spec == spec


def test_a_spec_without_storage_is_unaffected() -> None:
    spec = {"type": "docker", "image": "ghcr.io/acme/app:1"}

    assert MCPServerUpdate(json_spec=spec).json_spec == spec
