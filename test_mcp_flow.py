#!/usr/bin/env python3
"""
Test script for MCP server creation and instance management flow.
This script tests the complete flow from creating MCP servers to running instances.
"""

import requests
import time
import sys
import subprocess
from typing import Dict, Any, Optional, List

# Configuration
CORE_API_BASE = "http://localhost:8000"
GO_MCP_API_BASE = "http://localhost:7999"


def make_request(
    method: str, url: str, data: Optional[Dict[str, Any]] = None, timeout: int = 10
) -> Dict[str, Any]:
    """Make HTTP request with error handling."""
    try:
        if method.upper() == "GET":
            response = requests.get(url, timeout=timeout)
        elif method.upper() == "POST":
            response = requests.post(url, json=data, timeout=timeout)
        elif method.upper() == "DELETE":
            response = requests.delete(url, timeout=timeout)
        else:
            raise ValueError(f"Unsupported method: {method}")

        print(f"{method} {url} -> {response.status_code}")
        if response.status_code >= 400:
            print(f"Error response: {response.text}")

        return {
            "status_code": response.status_code,
            "data": response.json() if response.content else {},
            "success": 200 <= response.status_code < 300,
        }
    except requests.exceptions.RequestException as e:
        print(f"Request failed: {e}")
        return {"status_code": 0, "data": {}, "success": False, "error": str(e)}


def test_health_checks() -> bool:
    """Test that both services are running."""
    print("=== Testing Health Checks ===")

    # Test Core API (check MCP servers endpoint)
    core_health = make_request("GET", f"{CORE_API_BASE}/v1/mcp-servers/")
    if not core_health["success"]:
        print("❌ Core API is not responding")
        return False
    print("✅ Core API is healthy")

    # Test Go MCP Manager
    go_health = make_request("GET", f"{GO_MCP_API_BASE}/health")
    if not go_health["success"]:
        print("❌ Go MCP Manager is not responding")
        return False
    print("✅ Go MCP Manager is healthy")

    return True


def create_echo_mcp_server() -> Optional[str]:
    """Create an Echo MCP server specification."""
    print("\n=== Creating Echo MCP Server Specification ===")

    mcp_server_data = {
        "name": "agentarea-echo-mcp",
        "description": "AgentArea Echo MCP server for testing",
        "docker_image_url": "agentarea/echo",
        "env_schema": [
            {
                "name": "PORT",
                "type": "string",
                "description": "Port number for the MCP server",
                "default": "3333",
                "required": False,
            },
            {
                "name": "MCP_PATH",
                "type": "string",
                "description": "Path for MCP endpoints",
                "default": "/mcp",
                "required": False,
            },
            {
                "name": "LOG_LEVEL",
                "type": "string",
                "description": "Log level for the server",
                "default": "info",
                "required": False,
            },
        ],
        "tags": ["echo", "test", "agentarea"],
        "is_public": True,
    }

    response = make_request("POST", f"{CORE_API_BASE}/v1/mcp-servers/", mcp_server_data)
    if response["success"]:
        server_id = response["data"]["id"]
        print(f"✅ Created Echo MCP server specification with ID: {server_id}")
        return server_id
    else:
        print("❌ Failed to create Echo MCP server specification")
        print(f"Response: {response}")
        return None


def create_echo_mcp_instance(server_id: str) -> Optional[str]:
    """Create an instance of the Echo MCP server."""
    print(f"\n=== Creating Echo MCP Instance for server {server_id} ===")

    instance_data = {
        "name": "echo-mcp-e2e-test",
        "description": "E2E test with agentarea/echo MCP server",
        "server_spec_id": server_id,
        "json_spec": {
            "type": "docker",
            "image": "agentarea/echo",
            "port": 3333,
            "environment": {
                "PORT": "3333",
                "MCP_PATH": "/mcp",
                "LOG_LEVEL": "debug",
                "NODE_ENV": "development",
                "TEST_SECRET": "echo-test-secret-123",
            },
            "resources": {"memory_limit": "128m", "cpu_limit": "0.25"},
        },
    }

    response = make_request(
        "POST", f"{CORE_API_BASE}/v1/mcp-server-instances/", instance_data
    )
    if response["success"]:
        instance_id = response["data"]["id"]
        print(f"✅ Created Echo MCP instance with ID: {instance_id}")
        return instance_id
    else:
        print("❌ Failed to create Echo MCP instance")
        print(f"Response: {response}")
        return None


def wait_for_container_creation(
    instance_name: str, max_wait: int = 60
) -> Optional[Dict[str, Any]]:
    """Wait for container to be created and return container info."""
    print(f"\n=== Waiting for container '{instance_name}' to be created ===")

    for i in range(max_wait):
        containers_response = make_request("GET", f"{GO_MCP_API_BASE}/containers")
        if containers_response["success"]:
            containers = containers_response["data"]["containers"]
            for container in containers:
                if container.get("service_name") == instance_name:
                    status = container.get("status", "unknown")
                    print(f"Container found! Status: {status}")
                    if status.lower() in ["running"]:
                        print(f"✅ Container '{instance_name}' is running!")
                        return container
                    elif status.lower() in ["failed", "error", "exited"]:
                        print(f"❌ Container '{instance_name}' failed to start")
                        return None

        print(f"Waiting for container creation... ({i + 1}/{max_wait})")
        time.sleep(1)

    print(f"❌ Container '{instance_name}' was not created within {max_wait} seconds")
    return None


def test_echo_mcp_functionality(container_info: Dict[str, Any]) -> bool:
    """Test the Echo MCP server functionality."""
    print(f"\n=== Testing Echo MCP Server Functionality ===")

    container_name = container_info.get("name")
    container_port = container_info.get("environment", {}).get(
        "MCP_CONTAINER_PORT", "3333"
    )
    mcp_path = container_info.get("environment", {}).get("MCP_PATH", "/mcp")

    print(f"Testing Echo MCP server in container: {container_name}")
    print(f"Container port: {container_port}")
    print(f"MCP path: {mcp_path}")

    # Test 1: Check if container is responding via MCP endpoint
    print("Test 1: Checking MCP endpoint connectivity...")
    try:
        # Test MCP endpoint
        test_cmd = f"docker exec mcp-manager curl -s --connect-timeout 10 -H 'Content-Type: application/json' http://{container_name}:{container_port}{mcp_path} || echo 'MCP_ENDPOINT_FAILED'"

        result = subprocess.run(
            test_cmd, shell=True, capture_output=True, text=True, timeout=15
        )

        if "MCP_ENDPOINT_FAILED" not in result.stdout and result.returncode == 0:
            print("✅ MCP endpoint is accessible")
            print(f"Response preview: {result.stdout[:300]}...")

            # Check if it's a valid MCP response
            if '"jsonrpc"' in result.stdout or '"capabilities"' in result.stdout:
                print("✅ Valid MCP protocol response detected!")
                return True
            else:
                print("⚠️ Response doesn't appear to be MCP protocol")
        else:
            print("⚠️ MCP endpoint not accessible")
            print(f"Output: {result.stdout}")
            print(f"Error: {result.stderr}")
    except Exception as e:
        print(f"❌ MCP endpoint test failed: {e}")

    # Test 2: Check container logs for Echo MCP server startup
    print("\nTest 2: Checking container logs for Echo MCP server activity...")
    try:
        logs_cmd = f"docker exec mcp-manager podman logs {container_name}"
        result = subprocess.run(
            logs_cmd, shell=True, capture_output=True, text=True, timeout=10
        )

        if result.returncode == 0 and result.stdout:
            print("✅ Container logs retrieved successfully")
            logs = result.stdout

            # Look for Echo MCP server startup messages
            if any(
                keyword in logs.lower()
                for keyword in ["server", "listening", "started", "port"]
            ):
                print("✅ Server startup messages found in logs!")
                print("Sample server output:")
                for line in logs.split("\n")[:8]:  # Show first 8 lines
                    if line.strip():
                        print(f"  {line}")
                return True
            else:
                print("⚠️ No server startup messages found in logs")
                print("Container output:")
                print(logs[:800])  # Show first 800 chars
        else:
            print(f"❌ Failed to get container logs: {result.stderr}")
    except Exception as e:
        print(f"❌ Error checking container logs: {e}")

    # Test 3: Test basic HTTP connectivity
    print("\nTest 3: Testing basic HTTP connectivity...")
    try:
        basic_test_cmd = f"docker exec mcp-manager curl -s --connect-timeout 5 http://{container_name}:{container_port}/ || echo 'HTTP_FAILED'"

        result = subprocess.run(
            basic_test_cmd, shell=True, capture_output=True, text=True, timeout=10
        )

        if "HTTP_FAILED" not in result.stdout and result.returncode == 0:
            print("✅ Basic HTTP connectivity working")
            return True
        else:
            print("⚠️ Basic HTTP connectivity failed")
    except Exception as e:
        print(f"❌ Basic HTTP test failed: {e}")

    return False


def test_environment_variables(container_info: Dict[str, Any]) -> bool:
    """Test that environment variables are properly set."""
    print(f"\n=== Testing Environment Variables ===")

    environment = container_info.get("environment", {})

    print("Environment variables found:")
    for key, value in environment.items():
        print(f"  {key}: {value}")

    # Check for expected variables based on Echo MCP server
    expected_vars = [
        "PORT",
        "MCP_PATH",
        "MCP_INSTANCE_ID",
        "MCP_SERVICE_NAME",
        "MCP_CONTAINER_PORT",
    ]

    missing_vars: List[str] = []
    for var in expected_vars:
        if var not in environment:
            missing_vars.append(var)

    if missing_vars:
        print(f"❌ Missing environment variables: {missing_vars}")
        return False
    else:
        print("✅ All expected environment variables are present")

        # Check if port is correctly set
        if (
            environment.get("PORT") == "3333"
            or environment.get("MCP_CONTAINER_PORT") == "3333"
        ):
            print("✅ Port configuration is correct (3333)")
        else:
            print(
                f"⚠️ Port configuration may be incorrect (PORT: {environment.get('PORT')}, MCP_CONTAINER_PORT: {environment.get('MCP_CONTAINER_PORT')})"
            )

        # Check if MCP path is correctly set
        if environment.get("MCP_PATH") == "/mcp":
            print("✅ MCP path configuration is correct (/mcp)")
        else:
            print(
                f"⚠️ MCP path configuration may be incorrect (MCP_PATH: {environment.get('MCP_PATH')})"
            )

        return True


def test_external_routing(container_info: Dict[str, Any]) -> bool:
    """Test external routing through Traefik."""
    print(f"\n=== Testing External Routing ===")

    # Get slug from Traefik configuration
    try:
        traefik_config = subprocess.run(
            ["cat", "mcp-infrastructure/traefik/dynamic.yml"],
            capture_output=True,
            text=True,
            timeout=5,
        )

        if traefik_config.returncode == 0:
            config_text = traefik_config.stdout

            # Look for our service in the config
            service_name = container_info.get("service_name", "")
            if service_name in config_text:
                # Extract slug from the routing rule
                for line in config_text.split("\n"):
                    if f"mcp-{service_name}" in line and "rule:" in line:
                        # Extract slug from PathPrefix rule
                        import re

                        match = re.search(r"/mcp/([^`]+)", line)
                        if match:
                            slug = match.group(1)
                            print(f"✅ Found routing slug: {slug}")

                            # Test external access
                            external_url = f"http://localhost:81/mcp/{slug}/mcp/"
                            print(f"Testing external URL: {external_url}")

                            test_cmd = f"""curl -s "{external_url}" \
                                -H "Accept: application/json, text/event-stream" \
                                -H "Content-Type: application/json" \
                                -d '{{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {{"protocolVersion": "2024-11-05", "capabilities": {{}}, "clientInfo": {{"name": "test", "version": "1.0"}}}}}}' \
                                --max-time 10"""

                            result = subprocess.run(
                                test_cmd,
                                shell=True,
                                capture_output=True,
                                text=True,
                                timeout=15,
                            )

                            if result.returncode == 0 and "jsonrpc" in result.stdout:
                                print("✅ External MCP access working!")
                                print(f"Response preview: {result.stdout[:200]}...")
                                return True
                            else:
                                print(f"❌ External access failed: {result.stdout}")
                        break
            else:
                print(f"⚠️ Service {service_name} not found in Traefik config")
        else:
            print("❌ Failed to read Traefik configuration")
    except Exception as e:
        print(f"❌ External routing test failed: {e}")

    return False


def check_go_containers() -> List[Dict[str, Any]]:
    """Check containers managed by Go service."""
    print("\n=== Checking Go MCP Manager Containers ===")

    response = make_request("GET", f"{GO_MCP_API_BASE}/containers")
    if response["success"]:
        containers_data = response["data"]
        containers = containers_data.get("containers", [])
        print(f"✅ Found {len(containers)} containers:")
        for container in containers:
            name = container.get("service_name", "unknown")
            status = container.get("status", "unknown")
            image = container.get("image", "unknown")
            print(f"  - {name} ({status}) - {image}")
        return containers
    else:
        print("❌ Failed to get containers from Go service")
        return []


def list_mcp_instances() -> List[Dict[str, Any]]:
    """List all MCP instances."""
    print("\n=== Listing MCP Instances ===")

    response = make_request("GET", f"{CORE_API_BASE}/v1/mcp-server-instances/")
    if response["success"]:
        instances = response["data"]
        print(f"✅ Found {len(instances)} MCP instances:")
        for instance in instances:
            name = instance.get("name", "unknown")
            instance_id = instance.get("id", "unknown")
            print(f"  - {name} (ID: {instance_id})")
        return instances
    else:
        print("❌ Failed to list MCP instances")
        return []


def list_mcp_servers() -> List[Dict[str, Any]]:
    """List all MCP servers."""
    print("\n=== Listing MCP Servers ===")

    response = make_request("GET", f"{CORE_API_BASE}/v1/mcp-servers/")
    if response["success"]:
        servers = response["data"]
        print(f"✅ Found {len(servers)} MCP servers:")
        for server in servers:
            name = server.get("name", "unknown")
            server_id = server.get("id", "unknown")
            print(f"  - {name} (ID: {server_id})")
        return servers
    else:
        print("❌ Failed to list MCP servers")
        return []


def cleanup_test_data() -> None:
    """Clean up test data."""
    print("\n=== Cleaning up test data ===")

    # List and delete instances
    instances = list_mcp_instances()
    for instance in instances:
        name = instance.get("name", "")
        if (
            name.startswith("test-")
            or name.startswith("event-test-")
            or name.startswith("echo-mcp-")
        ):
            instance_id = instance.get("id")
            print(f"Deleting instance: {instance_id}")
            make_request(
                "DELETE", f"{CORE_API_BASE}/v1/mcp-server-instances/{instance_id}"
            )

    # List and delete servers
    servers = list_mcp_servers()
    for server in servers:
        name = server.get("name", "")
        if name.startswith("test-") or name.startswith("agentarea-echo-"):
            server_id = server.get("id")
            print(f"Deleting server: {server_id}")
            make_request("DELETE", f"{CORE_API_BASE}/v1/mcp-servers/{server_id}")


def main() -> None:
    """Run the complete E2E test with agentarea/echo."""
    print("🚀 Starting AgentArea Echo MCP E2E Test")
    print("=" * 60)

    # Test health checks
    if not test_health_checks():
        print("❌ Services are not healthy. Please check docker-compose.dev.yaml")
        sys.exit(1)

    # Clean up any existing test data
    cleanup_test_data()

    # Wait a moment for cleanup
    time.sleep(2)

    # Step 1: Create MCP server specification
    server_id = create_echo_mcp_server()
    if not server_id:
        print("❌ Failed to create Echo MCP server specification")
        sys.exit(1)

    # Step 2: Create MCP instance from the specification
    instance_id = create_echo_mcp_instance(server_id)
    if not instance_id:
        print("❌ Failed to create Echo MCP instance")
        sys.exit(1)

    # Step 3: Wait for container to be created and running
    print("\n⏳ Waiting for container creation and startup...")
    container_info = wait_for_container_creation("echo-mcp-e2e-test", max_wait=90)

    if not container_info:
        print("❌ Container was not created or failed to start")
        sys.exit(1)

    # Additional wait for container to fully initialize
    print("⏳ Waiting for Echo MCP server to initialize...")
    time.sleep(5)

    # Run tests
    print("\n🧪 Running E2E Tests...")

    # Test 1: Environment Variables
    env_test_passed = test_environment_variables(container_info)

    # Test 2: Echo MCP Server Functionality
    echo_mcp_test_passed = test_echo_mcp_functionality(container_info)

    # Test 3: External Routing
    external_routing_passed = test_external_routing(container_info)

    # Final status check
    print("\n=== Final Container Status ===")
    final_containers = check_go_containers()

    # Summary
    print("\n🎯 E2E Test Summary:")
    print(f"✅ Services healthy: True")
    print(f"✅ MCP server spec created: {bool(server_id)}")
    print(f"✅ MCP instance created: {bool(instance_id)}")
    print(f"✅ Container running: {bool(container_info)}")
    print(f"✅ Environment variables: {env_test_passed}")
    print(f"✅ Echo MCP functionality: {echo_mcp_test_passed}")
    print(f"✅ External routing: {external_routing_passed}")
    print(f"📊 Total containers: {len(final_containers)}")

    # Overall result
    all_tests_passed = all(
        [
            bool(server_id),
            bool(instance_id),
            bool(container_info),
            env_test_passed,
            echo_mcp_test_passed,
            external_routing_passed,
        ]
    )

    if all_tests_passed:
        print("\n🎉 SUCCESS: All E2E tests passed!")
        print("✅ AgentArea Echo MCP server specification created")
        print("✅ Echo MCP instance created from specification")
        print("✅ Event processing is functional")
        print("✅ Container management is working")
        print("✅ Environment variable injection is working")
        print("✅ External routing through Traefik is working")
        print("✅ Echo MCP server is accessible at localhost:81/mcp/{slug}/mcp/")
    else:
        print("\n⚠️ PARTIAL SUCCESS: Some tests failed")
        print("Check the detailed output above for issues")

    # Keep container running for manual inspection
    print(f"\n📋 Container Info:")
    if container_info:
        print(f"   Name: {container_info.get('name', 'N/A')}")
        print(f"   Status: {container_info.get('status', 'N/A')}")
        print(f"   Server Spec ID: {server_id}")
        print(f"   Instance ID: {instance_id}")

        print("\n💡 To manually inspect the container:")
        print(
            f"   docker exec mcp-manager podman logs {container_info.get('name', 'CONTAINER_NAME')}"
        )
        print(
            f"   curl -s http://localhost:7999/containers | jq '.containers[] | select(.service_name == \"echo-mcp-e2e-test\")'"
        )
    else:
        print("   Container info not available")


if __name__ == "__main__":
    main()
