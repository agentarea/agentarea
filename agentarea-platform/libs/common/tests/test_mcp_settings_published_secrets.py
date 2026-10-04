"""Sandbox and MCP gateway keys this repository once published refuse to load."""

import pytest
from agentarea_common.config.mcp import MCPSettings
from agentarea_common.config.sandbox import SandboxSettings
from pydantic import ValidationError

# env var -> the settings class and the field it populates, which is what the
# validator names in its error
KEYS = {
    "AGENTAREA_MCP_GATEWAY_SECRET": (MCPSettings, "GATEWAY_SECRET"),  # pragma: allowlist secret
    "AGENTAREA_SANDBOX_FILE_SECRET": (SandboxSettings, "FILE_SECRET"),  # pragma: allowlist secret
    "AGENTAREA_SANDBOX_CONTROL_SECRET": (  # pragma: allowlist secret
        SandboxSettings,
        "CONTROL_SECRET",
    ),
}


@pytest.mark.parametrize(("env_name", "target"), KEYS.items())
@pytest.mark.parametrize(
    "published",
    [
        "dev-sandbox-file-auth-secret-change-in-prod-000000",  # pragma: allowlist secret
        "agentarea-dev-mcp-gateway-secret-change-me",  # pragma: allowlist secret
    ],
)
def test_published_value_refuses_to_load(monkeypatch, env_name, target, published):
    settings_class, field = target
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(env_name, published)

    with pytest.raises(ValidationError, match=field):
        settings_class(_env_file=None)


def test_generated_value_loads(monkeypatch):
    for name in KEYS:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(
        "AGENTAREA_SANDBOX_FILE_SECRET",
        "q7Xk0m3v9Zr2Lp8sWc4Nh6Ty1Bd5Fg0J",  # pragma: allowlist secret
    )

    settings = SandboxSettings(_env_file=None)  # pyright: ignore[reportCallIssue]

    assert settings.FILE_SECRET is not None
