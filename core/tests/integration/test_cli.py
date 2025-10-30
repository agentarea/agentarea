"""Test script for the AgentArea CLI."""



def test_cli_imports():
    """Test that CLI components can be imported."""
    from agentarea_cli.main import AgentAreaClient, AuthConfig, cli

    assert AgentAreaClient is not None
    assert AuthConfig is not None
    assert cli is not None


def test_auth_config_creation():
    """Test that AuthConfig can be created."""
    from agentarea_cli.main import AuthConfig

    auth_config = AuthConfig()
    assert auth_config is not None


def test_client_creation():
    """Test that AgentAreaClient can be created."""
    from agentarea_cli.main import AgentAreaClient, AuthConfig

    auth_config = AuthConfig()
    client = AgentAreaClient("http://localhost:8000", auth_config)
    assert client is not None
