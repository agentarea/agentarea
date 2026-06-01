"""E2E tests for MCP server containerization.

These tests verify the complete flow:
1. Create MCP spec via API
2. Create MCP instance via API
3. Verify container is actually running via docker/podman
4. Delete instance via API
5. Verify container is removed

Auth uses the standard ``alice_client`` fixture (Ory Kratos session token)
shared with the rest of the e2e suite, so this file follows the same auth
flow as every other test instead of forging its own JWT.
"""

import logging
import os
import subprocess
import time
from typing import Any
from uuid import uuid4

import httpx
import pytest

logger = logging.getLogger(__name__)

pytestmark = [
    pytest.mark.skipif(
        bool(os.getenv("SKIP_DOCKER_TESTS") or os.getenv("CI")),
        reason="Docker tests skipped in CI or when SKIP_DOCKER_TESTS is set",
    ),
]


class ContainerRuntime:
    """Helper to interact with the local container runtime."""

    def __init__(self) -> None:
        self.runtime = self._detect_runtime()

    def _detect_runtime(self) -> str:
        for runtime in ("docker", "podman"):
            result = subprocess.run(
                ["which", runtime],
                capture_output=True,
            )
            if result.returncode == 0:
                return runtime
        raise RuntimeError("No container runtime found")

    def get_container_by_label(self, label: str) -> dict[str, Any] | None:
        """Find a container by label.

        Uses the ``{{json .}}`` Go template format (universal across Docker
        and Podman versions) rather than the modern ``--format json`` flag,
        which older daemons interpret as a literal string.
        """
        cmd = [
            self.runtime,
            "ps",
            "--filter",
            f"label={label}",
            "--format",
            "{{json .}}",
        ]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0 or not result.stdout.strip():
            return None
        import json

        try:
            for line in result.stdout.strip().split("\n"):
                return json.loads(line)
        except json.JSONDecodeError:
            return None
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
        except json.JSONDecodeError:
            return {}
        env_dict: dict[str, str] = {}
        for item in env_list:
            if "=" in item:
                key, value = item.split("=", 1)
                env_dict[key] = value
        return env_dict

    def container_exists(self, container_id: str) -> bool:
        """Check if a container exists (running or stopped)."""
        cmd = [self.runtime, "ps", "-a", "--filter", f"id={container_id}", "--format", "{{.ID}}"]
        result = subprocess.run(cmd, capture_output=True, text=True)
        return result.returncode == 0 and result.stdout.strip() != ""


@pytest.fixture
def container_runtime() -> ContainerRuntime:
    return ContainerRuntime()


def _find_container_for_instance(
    runtime: ContainerRuntime, instance_id: str
) -> tuple[str | None, dict[str, Any] | None]:
    """Locate the container backing an MCP instance.

    Tries label-based lookup first (the manager stamps standard labels)
    and falls back to scanning ``MCP_INSTANCE_ID`` env vars across
    running containers — both forms have been observed in the manager
    history.
    """
    for label in (f"mcp.instance.id={instance_id}", "mcp-managed=true"):
        container = runtime.get_container_by_label(label)
        if container:
            cid = container.get("Id") or container.get("ID")
            return cid, container

    listed = subprocess.run(
        [runtime.runtime, "ps", "--format", "{{.ID}}"],
        capture_output=True,
        text=True,
    )
    if listed.returncode != 0:
        return None, None

    for cid in listed.stdout.strip().split("\n"):
        cid = cid.strip()
        if not cid:
            continue
        env = runtime.get_container_env(cid)
        if env.get("MCP_INSTANCE_ID") == instance_id:
            inspect = subprocess.run(
                [runtime.runtime, "inspect", cid, "--format", "{{json .}}"],
                capture_output=True,
                text=True,
            )
            if inspect.returncode == 0:
                import json

                try:
                    payload = json.loads(inspect.stdout)
                except json.JSONDecodeError:
                    return cid, None
                if isinstance(payload, list):
                    return cid, payload[0] if payload else None
                return cid, payload
            return cid, None
    return None, None


@pytest.mark.integration
@pytest.mark.timeout(120)
def test_mcp_instance_container_lifecycle(
    alice_client: httpx.Client, container_runtime: ContainerRuntime
) -> None:
    """End-to-end MCP instance lifecycle: API → container running → delete → container gone."""
    unique_id = uuid4().hex[:8]

    spec_response = alice_client.post(
        "/v1/mcp-servers/",
        json={
            "name": f"test-container-spec-{unique_id}",
            "description": "Test spec for container lifecycle",
            "docker_image_url": "nginx:alpine",
            "version": "1.0.0",
        },
    )
    assert spec_response.status_code in (200, 201), (
        f"Failed to create spec: {spec_response.status_code} {spec_response.text}"
    )
    spec_id = spec_response.json()["id"]

    try:
        instance_response = alice_client.post(
            "/v1/mcp-server-instances/",
            json={
                "server_spec_id": str(spec_id),
                "name": f"test-container-instance-{unique_id}",
                "description": "Test instance for container lifecycle",
                "json_spec": {
                    "image": "nginx:alpine",
                    "port": 80,
                    "environment": {"NGINX_PORT": "80"},
                },
            },
        )
        assert instance_response.status_code in (200, 201, 202), (
            f"Failed to create instance: {instance_response.status_code} {instance_response.text}"
        )
        instance_id = instance_response.json()["id"]

        # The instance row has no top-level status field — running-state
        # lives on the actual container managed by the MCP manager. Wait
        # for the container to appear (the manager picks the create event
        # off the bus and provisions out-of-band).
        container_id: str | None = None
        for _ in range(60):
            cid, _container = _find_container_for_instance(container_runtime, instance_id)
            if cid:
                container_id = cid
                break
            time.sleep(1)
        assert container_id is not None, (
            f"No container found for MCP instance {instance_id} after 60s — "
            "MCP manager may not have provisioned it."
        )

        env = container_runtime.get_container_env(container_id)
        assert env.get("MCP_INSTANCE_ID") == instance_id, "Container missing MCP_INSTANCE_ID"
        assert "MCP_SERVICE_NAME" in env, "Container missing MCP_SERVICE_NAME"

        delete_response = alice_client.delete(f"/v1/mcp-server-instances/{instance_id}")
        assert delete_response.status_code in (200, 202, 204), (
            f"Failed to delete instance: {delete_response.text}"
        )

        time.sleep(3)
        assert not container_runtime.container_exists(container_id), (
            f"Container {container_id[:12]} should be removed after instance deletion"
        )
    finally:
        # Best-effort cleanup; the test has already asserted, and a stale
        # spec row will not affect subsequent runs (unique-id naming).
        try:
            alice_client.delete(f"/v1/mcp-servers/{spec_id}")
        except Exception as exc:
            logger.warning("cleanup: failed to delete spec %s: %s", spec_id, exc)


@pytest.mark.integration
@pytest.mark.timeout(60)
def test_multiple_mcp_instances_isolated(
    alice_client: httpx.Client, container_runtime: ContainerRuntime
) -> None:
    """Two MCP instances must run in separate containers with distinct IDs."""
    unique_id = uuid4().hex[:8]
    instances: list[tuple[str, str]] = []
    container_ids: list[str] = []

    try:
        for i in range(2):
            spec_response = alice_client.post(
                "/v1/mcp-servers/",
                json={
                    "name": f"test-isolation-spec-{i}-{unique_id}",
                    "description": f"Test spec for isolation {i}",
                    "docker_image_url": "nginx:alpine",
                    "version": "1.0.0",
                },
            )
            assert spec_response.status_code in (200, 201), (
                f"Failed to create spec {i}: {spec_response.status_code} {spec_response.text}"
            )
            spec_id = spec_response.json()["id"]

            instance_response = alice_client.post(
                "/v1/mcp-server-instances/",
                json={
                    "server_spec_id": str(spec_id),
                    "name": f"test-isolation-instance-{i}-{unique_id}",
                    "description": f"Test instance for isolation {i}",
                    "json_spec": {"image": "nginx:alpine", "port": 80},
                },
            )
            assert instance_response.status_code in (200, 201, 202), (
                f"Failed to create instance {i}: "
                f"{instance_response.status_code} {instance_response.text}"
            )
            instances.append((instance_response.json()["id"], spec_id))

        time.sleep(5)

        for instance_id, _ in instances:
            cid, _container = _find_container_for_instance(container_runtime, instance_id)
            if not cid:
                pytest.fail(f"No container found for instance {instance_id}")
            container_ids.append(cid)

        assert len(container_ids) == 2, f"Expected 2 containers, found {len(container_ids)}"
        assert container_ids[0] != container_ids[1], "Containers should have unique IDs"
    finally:
        # Best-effort cleanup; failures here should not mask the test result.
        for instance_id, spec_id in instances:
            try:
                alice_client.delete(f"/v1/mcp-server-instances/{instance_id}")
                alice_client.delete(f"/v1/mcp-servers/{spec_id}")
            except Exception as exc:
                logger.warning(
                    "cleanup: failed to delete instance %s / spec %s: %s",
                    instance_id,
                    spec_id,
                    exc,
                )
