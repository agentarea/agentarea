"""Reading an instance returns a secret reference as the name it references, never a value."""

import uuid
from datetime import UTC, datetime

from agentarea_api.api.v1.mcp_server_instances import MCPServerInstanceResponse
from agentarea_mcp.domain.mpc_server_instance_model import MCPServerInstance
from agentarea_mcp.domain.transport import MCPTransport


def test_the_reference_is_returned_unmasked_and_a_copied_secret_masked():
    instance = MCPServerInstance(
        name="conn",
        server_spec_id="00000000-0000-4000-8000-0000000000aa",
        transport=MCPTransport.URL,
        json_spec={
            "type": "url",
            "headers": {"Authorization": {"secret_name": "gh-token"}},  # pragma: allowlist secret
            "env_vars": ["X-Api-Key"],
        },
        workspace_id="ws",
        created_by="user",
    )
    instance.id = uuid.uuid4()
    instance.verification = {}
    instance.created_at = instance.updated_at = datetime.now(UTC)

    response = MCPServerInstanceResponse.from_domain(
        instance, secret_env_names={"Authorization", "X-Api-Key"}
    )

    assert response.json_spec["headers"] == {
        "Authorization": {"secret_name": "gh-token"},  # pragma: allowlist secret
        "X-Api-Key": "******",
    }
