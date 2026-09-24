"""Sandbox and MCP gateway keys this repository once published refuse to load."""

import pytest
from agentarea_common.config.mcp import MCPSettings
from pydantic import ValidationError

KEYS = ("MCP_GATEWAY_AUTH_SECRET", "SANDBOX_FILE_AUTH_SECRET", "SANDBOX_CONTROL_AUTH_SECRET")


@pytest.mark.parametrize("key", KEYS)
@pytest.mark.parametrize(
    "published",
    [
        "dev-sandbox-file-auth-secret-change-in-prod-000000",  # pragma: allowlist secret
        "agentarea-dev-mcp-gateway-secret-change-me",  # pragma: allowlist secret
    ],
)
def test_published_value_refuses_to_load(monkeypatch, key, published):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(key, published)

    with pytest.raises(ValidationError, match=key):
        MCPSettings(_env_file=None)


def test_generated_value_loads(monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("SANDBOX_FILE_AUTH_SECRET", "q7Xk0m3v9Zr2Lp8sWc4Nh6Ty1Bd5Fg0J")  # pragma: allowlist secret

    settings = MCPSettings(_env_file=None)

    assert settings.SANDBOX_FILE_AUTH_SECRET is not None
