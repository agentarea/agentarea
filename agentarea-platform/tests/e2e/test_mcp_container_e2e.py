"""E2E tests for MCP server containerization.

These tests verify the complete flow:
1. Create MCP spec via API
2. Create MCP instance via API  
3. Verify container is actually running via docker/podman
4. Delete instance via API
5. Verify container is removed
"""

import os
import subprocess
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import uuid4

import httpx
import jwt
import pytest


pytestmark = [
    pytest.mark.e2e,
    pytest.mark.skipif(
        os.getenv("SKIP_DOCKER_TESTS") or os.getenv("CI"),
        reason="Docker tests skipped in CI or SKIP_DOCKER_TESTS set",
    ),
]

API_BASE_URL = "http://localhost:8000"
TEST_WORKSPACE = "test-mcp-container-workspace"


def generate_test_token() -> str:
    """Generate a test JWT token for local development."""
    from cryptography.hazmat.primitives import serialization
    
    # AgentArea Kratos test key (local dev only)
    private_key_pem = """-----BEGIN EC PRIVATE KEY-----
MHcCAQEEIPO9DAeoH7kyeB7VJ1L2DMiaa+XlGTT+AZON21XY93gBoAoGCCqGSM49
AwEHoUQDQgAEMKBCTNIcKUSDii11ySs3526iDZ8AiTo7Tu6KPAqv7D7gS2XpJFbZ
iItSs3m9+9Ue6GnvHw/GW2ZZaVtszggXIw==
-----END EC PRIVATE KEY-----"""
    
    private_key = serialization.load_pem_private_key(private_key_pem.encode(), password=None)
    
    payload = {
        "sub": "e2e-test-user",
        "workspace_id": TEST_WORKSPACE,
        "iss": "https://agentarea.dev",
        "aud": "agentarea-api",
        "iat": datetime.now(UTC),
        "exp": datetime.now(UTC) + timedelta(minutes=60),
    }
    
    headers = {"kid": "agentarea-jwt-key-1"}
    return jwt.encode(payload, private_key, algorithm="ES256", headers=headers)


class ContainerRuntime:
    """Helper to interact with container runtime."""

    def __init__(self):
        self.runtime = self._detect_runtime()

    def _detect_runtime(self) -> str:
        for runtime in ["docker", "podman"]:
            result = subprocess.run(
                ["which", runtime],
                capture_output=True,
            )
            if result.returncode == 0:
                return runtime
        raise RuntimeError("No container runtime found")

    def get_container_by_label(self, label: str) -> dict[str, Any] | None:
        """Find container by label."""
        cmd = [
            self.runtime, "ps",
            "--filter", f"label={label}",
            "--format", "json"
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0 or not result.stdout.strip():
            return None

        import json
        try:
            lines = result.stdout.strip().split("\n")
            for line in lines:
                container = json.loads(line)
                return container
        except json.JSONDecodeError:
            return None

    def get_container_env(self, container_id: str) -> dict[str, str]:
        """Get container environment variables."""
        cmd = [self.runtime, "inspect", container_id, "--format", "{{json .Config.Env}}"]
        result = subprocess.run(cmd, capture_output=True, text=True)

        if result.returncode != 0:
            return {}

        import json
        try:
            env_list = json.loads(result.stdout)
            env_dict = {}
            for item in env_list:
                if "=" in item:
                    key, value = item.split("=", 1)
                    env_dict[key] = value
            return env_dict
        except json.JSONDecodeError:
            return {}

    def container_exists(self, container_id: str) -> bool:
        """Check if container exists (running or stopped)."""
        cmd = [self.runtime, "ps", "-a", "--filter", f"id={container_id}", "--format", "{{.ID}}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0 and result.stdout.strip() != ""


@pytest.fixture
def container_runtime() -> ContainerRuntime:
    return ContainerRuntime()


@pytest.fixture
def api_client():
    """Create authenticated HTTP client for testing."""
    token = generate_test_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": TEST_WORKSPACE,
    }
    
    client = httpx.Client(
        base_url=API_BASE_URL,
        timeout=60.0,
        headers=headers,
    )
    
    # Verify service is running
    try:
        response = client.get("/health")
        if response.status_code != 200:
            pytest.skip(f"AgentArea API not healthy: {response.status_code}")
    except Exception as e:
        pytest.skip(f"AgentArea API not running: {e}")
    
    yield client
    client.close()


@pytest.mark.e2e
@pytest.mark.timeout(120)
def test_mcp_instance_container_lifecycle(api_client, container_runtime: ContainerRuntime):
    """Test complete MCP instance container lifecycle.

    Steps:
    1. Create MCP server spec via API
    2. Create MCP instance via API
    3. Poll for instance to reach 'running' status
    4. Verify container exists with correct labels/env
    5. Delete instance via API
    6. Verify container is removed
    """
    unique_id = uuid4().hex[:8]

    # Step 1: Create MCP server spec
    spec_data = {
        "name": f"test-container-spec-{unique_id}",
        "description": "Test spec for container lifecycle",
        "docker_image_url": "nginx:alpine",
        "version": "1.0.0",
    }

    spec_response = api_client.post("/v1/mcp-servers/", json=spec_data)
    assert spec_response.status_code in [200, 201], f"Failed to create spec: {spec_response.text}"

    spec = spec_response.json()
    spec_id = spec["id"]

    try:
        # Step 2: Create MCP instance
        instance_data = {
            "server_spec_id": str(spec_id),
            "name": f"test-container-instance-{unique_id}",
            "description": "Test instance for container lifecycle",
            "json_spec": {
                "image": "nginx:alpine",
                "port": 80,
                "environment": {"NGINX_PORT": "80"},
            },
        }

        instance_response = api_client.post("/v1/mcp-server-instances/", json=instance_data)
        assert instance_response.status_code in [200, 201], f"Failed to create instance: {instance_response.text}"

        instance = instance_response.json()
        instance_id = instance["id"]

        print(f"\nCreated MCP instance: {instance_id}")

        # Step 3: Poll for instance to be running
        max_retries = 30
        retry_delay = 2
        running = False

        for i in range(max_retries):
            status_response = api_client.get(f"/v1/mcp-server-instances/{instance_id}")
            if status_response.status_code == 200:
                status_data = status_response.json()
                status = status_data.get("status", "unknown")
                print(f"  Attempt {i+1}: Status = {status}")

                if status == "running":
                    running = True
                    break
                elif status == "failed":
                    pytest.fail(f"Instance failed to start: {status_data}")

            time.sleep(retry_delay)

        assert running, f"Instance did not reach running status after {max_retries * retry_delay}s"

        # Step 4: Verify container exists
        # Look for container with MCP instance label
        container = None
        for _ in range(10):
            # Try different label formats
            for label in [f"mcp.instance.id={instance_id}", "mcp-managed=true"]:
                container = container_runtime.get_container_by_label(label)
                if container:
                    break
            if container:
                break
            time.sleep(1)

        # If not found by label, try to find by env var
        if not container:
            # List all containers and check env
            result = subprocess.run(
                [container_runtime.runtime, "ps", "--format", "{{.ID}}"],
                capture_output=True,
                text=True,
            )
            if result.returncode == 0:
                for cid in result.stdout.strip().split("\n"):
                    cid = cid.strip()
                    if not cid:
                        continue
                    env = container_runtime.get_container_env(cid)
                    if env.get("MCP_INSTANCE_ID") == instance_id:
                        # Found it, get full details
                        inspect_result = subprocess.run(
                            [container_runtime.runtime, "inspect", cid, "--format", "json"],
                            capture_output=True,
                            text=True,
                        )
                        if inspect_result.returncode == 0:
                            import json
                            container = json.loads(inspect_result.stdout)[0]
                            break

        assert container is not None, (
            f"No container found for MCP instance {instance_id}. "
            f"Container may not have been created by MCP manager."
        )

        container_id = container.get("Id") or container.get("ID")
        container_short_id = container_id[:12] if container_id else "unknown"

        print(f"  Found container: {container_short_id}")

        # Verify container is running
        state = container.get("State", {})
        if isinstance(state, dict):
            is_running = state.get("Running", False)
        else:
            # Try to get from container list
            result = subprocess.run(
                [container_runtime.runtime, "ps", "--filter", f"id={container_id}", "--format", "{{.State}}"],
                capture_output=True,
                text=True,
            )
            is_running = "running" in result.stdout.lower()

        assert is_running, f"Container {container_short_id} is not running"

        # Verify environment variables
        env = container_runtime.get_container_env(container_id)
        assert env.get("MCP_INSTANCE_ID") == instance_id, "Container missing MCP_INSTANCE_ID"
        assert "MCP_SERVICE_NAME" in env, "Container missing MCP_SERVICE_NAME"

        print(f"  ✓ Container verified: {container_short_id}")
        print(f"    - Status: running")
        print(f"    - MCP_INSTANCE_ID: {env.get('MCP_INSTANCE_ID')}")
        print(f"    - MCP_SERVICE_NAME: {env.get('MCP_SERVICE_NAME')}")

        # Step 5: Delete instance
        delete_response = api_client.delete(f"/v1/mcp-server-instances/{instance_id}")
        assert delete_response.status_code in [200, 202, 204], f"Failed to delete instance: {delete_response.text}"

        print(f"  Deleted instance: {instance_id}")

        # Step 6: Verify container is removed
        time.sleep(3)  # Wait for cleanup

        exists = container_runtime.container_exists(container_id)
        assert not exists, f"Container {container_short_id} should be removed after instance deletion"

        print(f"  ✓ Container removed: {container_short_id}")

    finally:
        # Cleanup spec if still exists
        try:
            api_client.delete(f"/v1/mcp-servers/{spec_id}")
        except Exception:
            pass


@pytest.mark.e2e
@pytest.mark.timeout(60)
def test_multiple_mcp_instances_isolated(api_client, container_runtime: ContainerRuntime):
    """Test that multiple MCP instances run in separate containers.

    Steps:
    1. Create two MCP specs and instances
    2. Verify each has its own container
    3. Verify containers have different IDs
    4. Cleanup
    """
    unique_id = uuid4().hex[:8]
    instances = []
    container_ids = []

    try:
        # Create two instances
        for i in range(2):
            # Create spec
            spec_data = {
                "name": f"test-isolation-spec-{i}-{unique_id}",
                "description": f"Test spec for isolation {i}",
                "docker_image_url": "nginx:alpine",
                "mcp_server_type": "http",
                "port": 80,
            }
            spec_response = api_client.post("/v1/mcp-server-specifications/", json=spec_data)
            assert spec_response.status_code == 201
            spec_id = spec_response.json()["id"]

            # Create instance
            instance_data = {
                "server_spec_id": spec_id,
                "name": f"test-isolation-instance-{i}-{unique_id}",
                "description": f"Test instance for isolation {i}",
                "json_spec": {
                    "image": "nginx:alpine",
                    "port": 80,
                },
            }
            instance_response = api_client.post("/v1/mcp-server-instances/", json=instance_data)
            assert instance_response.status_code == 201
            instance_id = instance_response.json()["id"]
            instances.append((instance_id, spec_id))

        print(f"\nCreated {len(instances)} MCP instances")

        # Wait for containers to start
        time.sleep(5)

        # Find containers for each instance
        for instance_id, _ in instances:
            # List all running containers
            result = subprocess.run(
                [container_runtime.runtime, "ps", "--format", "{{.ID}}"],
                capture_output=True,
                text=True,
            )

            found = False
            if result.returncode == 0:
                for cid in result.stdout.strip().split("\n"):
                    cid = cid.strip()
                    if not cid:
                        continue
                    env = container_runtime.get_container_env(cid)
                    if env.get("MCP_INSTANCE_ID") == instance_id:
                        container_ids.append(cid)
                        found = True
                        print(f"  Instance {instance_id[:8]}... → Container {cid[:12]}")
                        break

            if not found:
                pytest.fail(f"No container found for instance {instance_id}")

        # Verify containers are different
        assert len(container_ids) == 2, f"Expected 2 containers, found {len(container_ids)}"
        assert container_ids[0] != container_ids[1], "Containers should have unique IDs"

        print(f"  ✓ Containers are isolated (different container IDs)")

    finally:
        # Cleanup
        for instance_id, spec_id in instances:
            try:
                api_client.delete(f"/v1/mcp-server-instances/{instance_id}")
                api_client.delete(f"/v1/mcp-servers/{spec_id}")
            except Exception as e:
                print(f"  Cleanup warning: {e}")
