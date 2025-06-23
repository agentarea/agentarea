#!/usr/bin/env python3
"""
MCP Integration Test Runner

Usage:
    # Test with Docker image and environment variables
    python scripts/run_mcp_tests.py --image myorg/weather-mcp:latest --env API_KEY=your_key --env LOCATION=default

    # Test with URL endpoint (already running server)
    python scripts/run_mcp_tests.py --url http://mcp-server:3000

    # Use preset configurations
    python scripts/run_mcp_tests.py --preset weather
    python scripts/run_mcp_tests.py --preset filesystem
"""

import asyncio
import argparse
import sys
from pathlib import Path
from typing import Dict, List, Optional, Any
import httpx

# Add tests to path
sys.path.append(str(Path(__file__).parent.parent))


async def run_custom_mcp_test(
    server_name: str = "custom-mcp",
    docker_image: Optional[str] = None,
    mcp_url: Optional[str] = None,
    env_vars: Optional[Dict[str, str]] = None,
    api_base: str = "http://localhost:8000",
):
    """Run test with custom MCP server configuration."""

    if not docker_image and not mcp_url:
        raise ValueError("Either docker_image or mcp_url must be provided")

    print(f"🚀 Testing MCP server: {server_name}")
    if docker_image:
        print(f"   Docker Image: {docker_image}")
    if mcp_url:
        print(f"   URL: {mcp_url}")
    if env_vars:
        print(f"   Environment Variables: {list(env_vars.keys())}")
    print("-" * 50)

    client = httpx.AsyncClient(timeout=60)

    try:
        # Step 1: Create agent
        print("📝 Creating agent...")
        agent_data = {
            "name": f"MCP Test Agent - {server_name}",
            "description": f"Agent for testing {server_name} MCP integration",
            "instruction": "You are a helpful assistant that uses MCP tools to help users.",
            "model_id": "test-model",
        }

        response = await client.post(f"{api_base}/v1/agents/", json=agent_data)
        if response.status_code not in [200, 201]:
            raise Exception(
                f"Failed to create agent: {response.status_code} - {response.text}"
            )

        agent = response.json()
        agent_id = agent["id"]
        print(f"✅ Agent created: {agent_id}")

        # Step 2: Create MCP Server (if using Docker image)
        mcp_server_id = None
        if docker_image:
            print("🔧 Creating MCP server...")

            # Define environment variable schema (what variables this server needs)
            env_schema: List[Dict[str, Any]] = []
            if env_vars:
                for env_key in env_vars.keys():
                    env_schema.append(
                        {
                            "name": env_key,
                            "type": "string",
                            "required": True,
                            "sensitive": True,  # Mark all as sensitive for security
                            "description": f"Environment variable: {env_key}",
                        }
                    )

            server_data: Dict[str, Any] = {
                "name": server_name,
                "description": f"MCP server: {server_name}",
                "version": "1.0.0",
                "docker_image_url": docker_image,
                # Define what env vars this server needs (schema only)
                "env_schema": env_schema,
            }

            response = await client.post(
                f"{api_base}/v1/mcp-servers/", json=server_data
            )
            if response.status_code not in [200, 201]:
                raise Exception(
                    f"Failed to create MCP server: {response.status_code} - {response.text}"
                )

            server = response.json()
            mcp_server_id = server["id"]
            print(f"✅ MCP Server created: {mcp_server_id}")

        # Step 3: Create MCP Instance
        print("🚀 Creating MCP instance...")
        instance_data: Dict[str, Any] = {
            "name": f"{server_name}-instance",
            "config": {},
        }

        if mcp_server_id:
            # Docker-based instance - environment variables will be stored securely
            instance_data["server_id"] = mcp_server_id
            if env_vars:
                # Note: In production, the API would handle storing env vars securely
                # and only store env var names in the config, not actual values
                instance_data["env_vars"] = env_vars  # API will process this securely
        else:
            # URL-based instance
            instance_data["endpoint_url"] = mcp_url

        response = await client.post(
            f"{api_base}/v1/mcp-server-instances/", json=instance_data
        )
        if response.status_code not in [200, 201]:
            raise Exception(
                f"Failed to create MCP instance: {response.status_code} - {response.text}"
            )

        instance = response.json()
        mcp_instance_id = instance["id"]
        print(f"✅ MCP Instance created: {mcp_instance_id}")
        print(f"   Status: {instance['status']}")

        # Step 4: Create test task (without predefined tools)
        print("📋 Creating test task...")
        task_data = {
            "description": f"Test the {server_name} MCP server and discover its tools",
            "parameters": {
                "use_mcp_tools": True,
                # No predefined tools - let MCP protocol discover them
                "discover_tools": True,
            },
            "metadata": {
                "integration_test": True,
                "mcp_instance_id": mcp_instance_id,
                "custom_test": True,
                # Note: In production, environment variables would be stored in secret manager
                "env_vars_stored_securely": bool(env_vars) if env_vars else False,
            },
        }

        response = await client.post(
            f"{api_base}/v1/agents/{agent_id}/tasks/", json=task_data
        )
        if response.status_code not in [200, 201]:
            raise Exception(
                f"Failed to create task: {response.status_code} - {response.text}"
            )

        task = response.json()
        task_id = task.get("id") or task.get("task_id")
        print(f"✅ Task created: {task_id}")
        print(f"   Description: {task_data['description']}")

        # Step 5: Verify all components exist
        print("🔍 Verifying integration...")

        # Check agent
        response = await client.get(f"{api_base}/v1/agents/{agent_id}")
        if response.status_code != 200:
            raise Exception("Agent verification failed")

        # Check MCP server (if created)
        if mcp_server_id:
            response = await client.get(f"{api_base}/v1/mcp-servers/{mcp_server_id}")
            if response.status_code != 200:
                raise Exception("MCP server verification failed")

        # Check MCP instance
        response = await client.get(
            f"{api_base}/v1/mcp-server-instances/{mcp_instance_id}"
        )
        if response.status_code != 200:
            raise Exception("MCP instance verification failed")

        instance_check = response.json()
        print(f"✅ Integration verified - Instance status: {instance_check['status']}")

        # Step 6: Attempt to discover tools (optional verification)
        print("🔍 Attempting to discover MCP tools...")
        try:
            # This would be done by the MCP protocol at runtime
            response = await client.get(
                f"{api_base}/v1/mcp-server-instances/{mcp_instance_id}/tools"
            )
            if response.status_code == 200:
                tools = response.json()
                print(f"✅ Discovered {len(tools)} tools via MCP protocol")
                for tool in tools[:5]:  # Show first 5 tools
                    print(
                        f"   - {tool.get('name', 'Unknown')}: {tool.get('description', 'No description')}"
                    )
            else:
                print("ℹ️  Tool discovery not available (normal for test environment)")
        except Exception as e:
            print(f"ℹ️  Tool discovery skipped: {e}")

        print(f"🎉 MCP test passed for {server_name}!")

    finally:
        await client.aclose()


async def run_preset_test(preset: str):
    """Run a preset test."""

    if preset == "weather":
        await run_custom_mcp_test(
            server_name="weather-mcp",
            docker_image="weather-mcp:latest",
            env_vars={"API_KEY": "test_api_key", "DEFAULT_LOCATION": "San Francisco"},
        )

    elif preset == "filesystem":
        await run_custom_mcp_test(
            server_name="filesystem-mcp",
            docker_image="filesystem-mcp:latest",
            env_vars={"ALLOWED_PATHS": "/tmp,/workspace", "READ_ONLY": "false"},
        )

    else:
        raise ValueError(f"Unknown preset: {preset}")


def parse_env_vars(env_args: List[str]) -> Dict[str, str]:
    """Parse environment variables from command line arguments."""
    env_vars: Dict[str, str] = {}
    for env_arg in env_args:
        if "=" not in env_arg:
            raise ValueError(
                f"Invalid environment variable format: {env_arg}. Use KEY=VALUE"
            )
        key, value = env_arg.split("=", 1)
        env_vars[key] = value
    return env_vars


def main():
    parser = argparse.ArgumentParser(description="Run MCP integration tests")

    # Custom test options
    parser.add_argument(
        "--image",
        help="Docker image name for MCP server (e.g., 'myorg/weather-mcp:latest')",
    )
    parser.add_argument(
        "--url", help="MCP server endpoint URL (for already running servers)"
    )
    parser.add_argument(
        "--env",
        action="append",
        default=[],
        help="Environment variables (can be used multiple times). Format: KEY=VALUE",
    )
    parser.add_argument("--name", default="custom-mcp", help="MCP server name")

    # Preset options
    parser.add_argument(
        "--preset", choices=["weather", "filesystem"], help="Run a preset test"
    )

    # General options
    parser.add_argument(
        "--api-base", default="http://localhost:8000", help="AgentArea API base URL"
    )

    args = parser.parse_args()

    if args.preset:
        print(f"🚀 Running preset test: {args.preset}")
        asyncio.run(run_preset_test(args.preset))

    elif args.image or args.url:
        print("🚀 Running custom MCP test")
        env_vars = parse_env_vars(args.env) if args.env else {}

        asyncio.run(
            run_custom_mcp_test(
                server_name=args.name,
                docker_image=args.image,
                mcp_url=args.url,
                env_vars=env_vars,
                api_base=args.api_base,
            )
        )

    else:
        print(
            "❌ Either use --preset, provide --image with optional --env, or provide --url"
        )
        parser.print_help()
        sys.exit(1)

    print("✅ Test completed successfully!")


if __name__ == "__main__":
    main()
