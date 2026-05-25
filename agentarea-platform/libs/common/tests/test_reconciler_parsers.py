import pytest
import tempfile
from pathlib import Path

from agentarea_common.reconciler.parsers import parse_yaml, YAMLValidationError


def test_parse_mcp_servers_yaml():
    yaml_content = """
mcp_servers:
  - name: test-mcp
    description: "Test MCP server"
    docker_image_url: ghcr.io/test/mcp
    version: "1.0.0"
"""
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        specs = parse_yaml(Path(f.name), "mcp_servers")
        assert len(specs) == 1
        assert specs[0]["name"] == "test-mcp"
        assert specs[0]["docker_image_url"] == "ghcr.io/test/mcp"


def test_parse_agents_yaml():
    yaml_content = """
agents:
  - name: test-agent
    description: "Test agent"
    instruction: "You are a test agent."
    model: claude-sonnet-4-20250514
    tools:
      - type: code
        name: file_read
"""
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        specs = parse_yaml(Path(f.name), "agents")
        assert len(specs) == 1
        assert specs[0]["name"] == "test-agent"
        assert specs[0]["tools"][0]["type"] == "code"


def test_parse_invalid_yaml_raises():
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write("not: [valid: yaml: {{")
        f.flush()
        with pytest.raises(YAMLValidationError):
            parse_yaml(Path(f.name), "mcp_servers")


def test_parse_missing_required_field_raises():
    yaml_content = """
mcp_servers:
  - description: "Missing name field"
"""
    with tempfile.NamedTemporaryFile(suffix=".yaml", mode="w", delete=False) as f:
        f.write(yaml_content)
        f.flush()
        with pytest.raises(YAMLValidationError, match="name"):
            parse_yaml(Path(f.name), "mcp_servers")
