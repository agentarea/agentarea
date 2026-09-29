r"""json_spec that Postgres could not read back is refused with a 422, not stored.

An OpenAPI fuzz run created an instance whose json_spec held ``\u0000``; the
column accepted it and the mcp-manager idle sweep, which reads
``json_spec->>'type'`` across all instances, failed on every tick afterwards.
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

BAD_SPECS = [{"type": "docker", "environment": {"A": "x\x00"}}, {"type": "url", "x": "\ud958"}]


@pytest.mark.parametrize("spec", BAD_SPECS)
def test_instance_create_refuses_unstorable_text(spec) -> None:
    with pytest.raises(ValidationError, match=r"NUL|surrogate"):
        MCPServerInstanceCreate(name="i", server_spec_id=uuid4(), json_spec=spec)


@pytest.mark.parametrize("spec", BAD_SPECS)
def test_instance_update_refuses_unstorable_text(spec) -> None:
    spec = {k: v for k, v in spec.items() if k != "type"}
    with pytest.raises(ValidationError, match=r"NUL|surrogate"):
        MCPServerInstanceUpdate(json_spec=spec)


@pytest.mark.parametrize("spec", BAD_SPECS)
def test_server_create_and_update_refuse_unstorable_text(spec) -> None:
    with pytest.raises(ValidationError, match=r"NUL|surrogate"):
        MCPServerCreate(name="s", version="1", json_spec=spec)
    with pytest.raises(ValidationError, match=r"NUL|surrogate"):
        MCPServerUpdate(json_spec=spec)


def test_ordinary_specs_still_validate() -> None:
    spec = {"type": "docker", "environment": {"TOKEN": "ключ"}}
    assert MCPServerInstanceCreate(name="i", server_spec_id=uuid4(), json_spec=spec).json_spec == spec
    assert MCPServerUpdate(json_spec=spec).json_spec == spec


def test_instance_update_rejects_imported_runtime_fields() -> None:
    with pytest.raises(ValidationError, match=r"package|port|source"):
        MCPServerInstanceUpdate(
            json_spec={
                "port": 8080,
                "package": {"ecosystem": "npm"},
                "source": {"type": "command"},
            }
        )
