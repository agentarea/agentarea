"""Unit tests for the MCP-instance consumer reverse-lookup matching logic."""

from types import SimpleNamespace
from uuid import uuid4

from agentarea_api.api.v1.mcp_server_instances import _mcp_config_matches


def _instance(instance_id, name):
    return SimpleNamespace(id=instance_id, name=name)


def test_matches_by_uuid():
    iid = uuid4()
    inst = _instance(iid, "github")
    assert _mcp_config_matches({"type": "mcp", "name": str(iid)}, inst) is True


def test_matches_by_name():
    inst = _instance(uuid4(), "github")
    assert _mcp_config_matches({"type": "mcp", "name": "github"}, inst) is True


def test_non_mcp_type_never_matches():
    inst = _instance(uuid4(), "github")
    assert _mcp_config_matches({"type": "code", "name": "github"}, inst) is False


def test_missing_name_never_matches():
    inst = _instance(uuid4(), "github")
    assert _mcp_config_matches({"type": "mcp"}, inst) is False


def test_unrelated_ref_does_not_match():
    inst = _instance(uuid4(), "github")
    assert _mcp_config_matches({"type": "mcp", "name": str(uuid4())}, inst) is False
    assert _mcp_config_matches({"type": "mcp", "name": "slack"}, inst) is False
