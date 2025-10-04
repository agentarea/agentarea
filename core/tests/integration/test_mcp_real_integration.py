"""
Real MCP Integration Test

Tests the complete workflow with a real MCP server:
1. Create agent
2. Deploy real MCP server (with Dockerfile)
3. Execute task using MCP tools
4. Verify task completion
"""

import asyncio
from typing import Any

import httpx
import pytest


class MCPRealIntegrationTest:
    """Test class for real MCP integration."""

    def __init__(self, api_base: str = "http://localhost:8000"):
        self.api_base = api_base
        self.client: httpx.AsyncClient | None = None
        self.agent_id: str | None = None
        self.mcp_server_id: str | None = None
        self.mcp_instance_id: str | None = None
        self.task_id: str | None = None

    async def setup(self):
        """Setup test client."""
        self.client = httpx.AsyncClient(timeout=60)

    async def cleanup(self):
        """Cleanup resources."""
        if self.client:
            await self.client.aclose()

    async def create_test_agent(self) -> bool:
        """Create a test agent for MCP integration."""
        if not self.client:
            print("❌ Client not initialized")
            return False

        # Create or get Ollama model and instance
        model_id = await self._get_or_create_model()
        if not model_id:
            print("❌ Failed to get or create model")
            return False

        instance_id = await self._create_model_instance(model_id)
        if not instance_id:
            print("❌ Failed to create model instance")
            return False

        agent_data = {
            "name": "MCP Test Agent",
            "description": "Agent for testing real MCP integration",
            "instruction": "You are a helpful assistant that uses MCP tools to help users.",
            "model_id": instance_id,
        }

        response = await self.client.post(f"{self.api_base}/v1/agents/", json=agent_data)
        if response.status_code in [200, 201]:
            agent = response.json()
            self.agent_id = agent["id"]
            print(f"✅ Agent created: {self.agent_id}")
            return True
        else:
            print(f"❌ Failed to create agent: {response.status_code} - {response.text}")
            return False

    async def deploy_mcp_server(
        self,
        server_name: str,
        dockerfile_content: str,
        mcp_endpoint_url: str,
        tools_metadata: list[dict[str, Any]],
    ) -> bool:
        """Deploy a real MCP server with Dockerfile."""
        if not self.client:
            print("❌ Client not initialized")
            return False

        # Create MCP Server definition
        server_data = {
            "name": server_name,
            "description": f"Real MCP server: {server_name}",
            "version": "1.0.0",
            "docker_image_url": f"{server_name}:latest",  # Will be built from Dockerfile
            "dockerfile_content": dockerfile_content,  # For building the image
            "tools_metadata": tools_metadata,
        }

        # Create server
        response = await self.client.post(f"{self.api_base}/v1/mcp-servers/", json=server_data)
        if response.status_code not in [200, 201]:
            print(f"❌ Failed to create MCP server: {response.status_code} - {response.text}")
            return False

        server = response.json()
        self.mcp_server_id = server["id"]
        print(f"✅ MCP Server created: {self.mcp_server_id}")

        # Create and deploy instance
        instance_data = {
            "name": f"{server_name}-instance",
            "server_spec_id": self.mcp_server_id,
            "json_spec": {
                "type": "docker",
                "image": f"{server_name}:latest",
                "port": 3000,
                "endpoint_url": mcp_endpoint_url,
                "environment": {"PORT": "3000"},
                "resources": {"memory_limit": "256m", "cpu_limit": "0.5"},
            },
        }

        response = await self.client.post(
            f"{self.api_base}/v1/mcp-server-instances/", json=instance_data
        )
        if response.status_code not in [200, 201]:
            print(f"❌ Failed to create MCP instance: {response.status_code} - {response.text}")
            return False

        instance = response.json()
        self.mcp_instance_id = instance["id"]
        print(f"✅ MCP Instance created: {self.mcp_instance_id}")
        print(f"   Status: {instance['status']}")

        # Wait for deployment (in real scenario)
        print("⏳ Waiting for MCP server deployment...")
        await asyncio.sleep(5)  # Give time for deployment

        return True

    async def execute_mcp_task(self, task_description: str, expected_tools: list[str]) -> bool:
        """Execute a task that should use MCP tools."""
        if not self.client:
            print("❌ Client not initialized")
            return False

        task_data = {
            "description": task_description,
            "parameters": {"use_mcp_tools": True, "expected_tools": expected_tools},
            "metadata": {"integration_test": True, "mcp_server_id": self.mcp_server_id},
        }

        response = await self.client.post(
            f"{self.api_base}/v1/agents/{self.agent_id}/tasks/", json=task_data
        )
        if response.status_code not in [200, 201]:
            print(f"❌ Failed to create task: {response.status_code} - {response.text}")
            return False

        task = response.json()
        self.task_id = task.get("id") or task.get("task_id")
        print(f"✅ Task created: {self.task_id}")
        print(f"   Description: {task_description}")

        return True

    async def verify_mcp_integration(self) -> bool:
        """Verify that MCP integration is working."""
        if not self.client:
            print("❌ Client not initialized")
            return False

        if not all([self.agent_id, self.mcp_server_id, self.mcp_instance_id]):
            print("❌ Missing required components for verification")
            return False

        # Check agent
        agent_response = await self.client.get(f"{self.api_base}/v1/agents/{self.agent_id}")
        if agent_response.status_code != 200:
            print("❌ Agent not accessible")
            return False

        # Check MCP server
        mcp_response = await self.client.get(f"{self.api_base}/v1/mcp-servers/{self.mcp_server_id}")
        if mcp_response.status_code != 200:
            print("❌ MCP server not accessible")
            return False

        # Check MCP instance
        instance_response = await self.client.get(
            f"{self.api_base}/v1/mcp-server-instances/{self.mcp_instance_id}"
        )
        if instance_response.status_code != 200:
            print("❌ MCP instance not accessible")
            return False

        instance = instance_response.json()
        print("✅ MCP Integration verified")
        print(f"   Instance status: {instance['status']}")

        return True

    async def _get_or_create_model(self) -> str | None:
        """Get existing or create new Ollama model using new 4-entity architecture."""
        if not self.client:
            print("❌ Client not initialized")
            return None

        # Step 1: Get or find Ollama provider spec
        response = await self.client.get(f"{self.api_base}/v1/provider-specs/")
        if response.status_code != 200:
            print(f"❌ Failed to get provider specs: {response.status_code}")
            return None

        provider_specs = response.json()
        ollama_provider_spec = None
        for spec in provider_specs:
            if spec.get("provider_key") == "ollama":
                ollama_provider_spec = spec
                break

        if not ollama_provider_spec:
            print("❌ Ollama provider specification not found")
            return None

        provider_spec_id = ollama_provider_spec["id"]
        print(f"✅ Found Ollama provider spec: {provider_spec_id}")

        # Step 2: Check for existing provider config
        response = await self.client.get(
            f"{self.api_base}/v1/provider-configs/", params={"provider_spec_id": provider_spec_id}
        )

        provider_config_id = None
        if response.status_code == 200:
            configs = response.json()
            if configs:
                provider_config_id = configs[0]["id"]
                print(f"✅ Found existing provider config: {provider_config_id}")

        # Step 3: Create provider config if needed
        if not provider_config_id:
            config_data = {
                "provider_spec_id": provider_spec_id,
                "name": "Ollama Local",
                "api_key": "not-needed-for-ollama",
                "endpoint_url": "http://host.docker.internal:11434",
                "is_public": True,
            }

            response = await self.client.post(
                f"{self.api_base}/v1/provider-configs/", json=config_data
            )
            if response.status_code in [200, 201]:
                config = response.json()
                provider_config_id = config["id"]
                print(f"✅ Created provider config: {provider_config_id}")
            else:
                print(
                    f"❌ Failed to create provider config: {response.status_code} - {response.text}"
                )
                return None

        return provider_config_id

    async def _create_model_instance(self, provider_config_id: str) -> str | None:
        """Create model instance using new 4-entity architecture."""
        if not self.client:
            print("❌ Client not initialized")
            return None

        import uuid

        # Step 1: Get model specs for the provider
        response = await self.client.get(f"{self.api_base}/v1/provider-specs/with-models")
        if response.status_code != 200:
            print(f"❌ Failed to get provider specs with models: {response.status_code}")
            return None

        provider_specs = response.json()
        model_spec = None

        # Look for any available model in Ollama provider
        for spec in provider_specs:
            if spec.get("provider_key") == "ollama":
                models = spec.get("models", [])
                if models:
                    # Try to find qwen first, then fallback to any available model
                    for model in models:
                        if "qwen" in model.get("model_name", "").lower():
                            model_spec = model
                            break
                    # If no qwen found, use first available model
                    if not model_spec and models:
                        model_spec = models[0]
                        print(f"⚠️  Using fallback model: {model_spec.get('model_name', 'unknown')}")
                break

        if not model_spec:
            print("❌ No model specification found for Ollama")
            return None

        model_spec_id = model_spec["id"]
        model_name = model_spec.get("model_name", "unknown")
        print(f"✅ Found model spec: {model_name} ({model_spec_id})")

        # Step 2: Create model instance
        instance_data = {
            "provider_config_id": provider_config_id,
            "model_spec_id": model_spec_id,
            "name": f"test-{model_name}-instance-{uuid.uuid4().hex[:8]}",
            "description": f"Test {model_name} instance for MCP testing",
            "is_public": True,
        }

        response = await self.client.post(
            f"{self.api_base}/v1/model-instances/", json=instance_data
        )
        if response.status_code in [200, 201]:
            instance = response.json()
            print(f"✅ Created model instance: {instance['id']}")
            return str(instance.get("id"))
        else:
            print(f"❌ Failed to create model instance: {response.status_code} - {response.text}")
            return None


@pytest.mark.asyncio
async def test_weather_mcp_integration():
    """Test integration with a weather MCP server."""

    # Weather MCP server Dockerfile
    dockerfile_content = """
FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .

EXPOSE 3000

CMD ["python", "weather_mcp_server.py"]
"""

    # Weather tools metadata
    tools_metadata = [
        {
            "name": "get_weather",
            "description": "Get current weather for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {
                        "type": "string",
                        "description": "City name or coordinates",
                    },
                    "units": {
                        "type": "string",
                        "description": "Temperature units (celsius/fahrenheit)",
                        "default": "celsius",
                    },
                },
                "required": ["location"],
            },
        },
        {
            "name": "get_forecast",
            "description": "Get weather forecast for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"},
                    "days": {
                        "type": "integer",
                        "description": "Number of days",
                        "default": 3,
                    },
                },
                "required": ["location"],
            },
        },
    ]

    test = MCPRealIntegrationTest()
    await test.setup()

    try:
        # Step 1: Create agent
        assert await test.create_test_agent(), "Failed to create agent"

        # Step 2: Deploy weather MCP server
        assert await test.deploy_mcp_server(
            server_name="weather-service",
            dockerfile_content=dockerfile_content,
            mcp_endpoint_url="http://weather-service:3000",
            tools_metadata=tools_metadata,
        ), "Failed to deploy MCP server"

        # Step 3: Execute weather task
        assert await test.execute_mcp_task(
            task_description="Get the current weather in Moscow and tell me if I need a jacket",
            expected_tools=["get_weather"],
        ), "Failed to execute MCP task"

        # Step 4: Verify integration
        assert await test.verify_mcp_integration(), "MCP integration verification failed"

        print("🎉 Weather MCP integration test passed!")

    finally:
        await test.cleanup()


@pytest.mark.asyncio
async def test_filesystem_mcp_integration():
    """Test integration with a filesystem MCP server."""

    # Filesystem MCP server Dockerfile
    dockerfile_content = """
FROM python:3.11-slim

WORKDIR /app

# Install required packages
RUN pip install fastapi uvicorn aiofiles

COPY filesystem_mcp_server.py .

EXPOSE 3000

CMD ["uvicorn", "filesystem_mcp_server:app", "--host", "0.0.0.0", "--port", "3000"]
"""

    # Filesystem tools metadata
    tools_metadata = [
        {
            "name": "read_file",
            "description": "Read contents of a file",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "File path"}},
                "required": ["path"],
            },
        },
        {
            "name": "write_file",
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"},
                },
                "required": ["path", "content"],
            },
        },
        {
            "name": "list_directory",
            "description": "List files in a directory",
            "parameters": {
                "type": "object",
                "properties": {"path": {"type": "string", "description": "Directory path"}},
                "required": ["path"],
            },
        },
    ]

    test = MCPRealIntegrationTest()
    await test.setup()

    try:
        # Step 1: Create agent
        assert await test.create_test_agent(), "Failed to create agent"

        # Step 2: Deploy filesystem MCP server
        assert await test.deploy_mcp_server(
            server_name="filesystem-service",
            dockerfile_content=dockerfile_content,
            mcp_endpoint_url="http://filesystem-service:3000",
            tools_metadata=tools_metadata,
        ), "Failed to deploy MCP server"

        # Step 3: Execute filesystem task
        assert await test.execute_mcp_task(
            task_description="Create a file called 'test.txt' with content 'Hello MCP!' and then read it back",
            expected_tools=["write_file", "read_file"],
        ), "Failed to execute MCP task"

        # Step 4: Verify integration
        assert await test.verify_mcp_integration(), "MCP integration verification failed"

        print("🎉 Filesystem MCP integration test passed!")

    finally:
        await test.cleanup()


@pytest.mark.asyncio
async def test_custom_mcp_integration():
    """Test integration with a custom MCP server using provided Dockerfile and URL."""

    # This can be customized for specific MCP servers
    custom_dockerfile = """
FROM nginx:alpine

COPY nginx.conf /etc/nginx/nginx.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
"""

    # Custom tools - can be modified based on actual MCP server
    tools_metadata = [
        {
            "name": "custom_tool",
            "description": "A custom MCP tool",
            "parameters": {
                "type": "object",
                "properties": {"input": {"type": "string", "description": "Input parameter"}},
                "required": ["input"],
            },
        }
    ]

    test = MCPRealIntegrationTest()
    await test.setup()

    try:
        # Step 1: Create agent
        assert await test.create_test_agent(), "Failed to create agent"

        # Step 2: Deploy custom MCP server
        assert await test.deploy_mcp_server(
            server_name="nginx-mcp-service",  # Use existing image
            dockerfile_content=custom_dockerfile,
            mcp_endpoint_url="http://nginx-mcp:3000",  # This can be customized
            tools_metadata=tools_metadata,
        ), "Failed to deploy MCP server"

        # Step 3: Execute custom task
        assert await test.execute_mcp_task(
            task_description="Use the custom MCP tool to process some data",
            expected_tools=["custom_tool"],
        ), "Failed to execute MCP task"

        # Step 4: Verify integration
        assert await test.verify_mcp_integration(), "MCP integration verification failed"

        print("🎉 Custom MCP integration test passed!")

    finally:
        await test.cleanup()


if __name__ == "__main__":
    """Run tests directly for development."""

    async def run_tests():
        print("🚀 Running MCP Real Integration Tests")
        print("=" * 50)

        try:
            await test_weather_mcp_integration()
            print()
            await test_filesystem_mcp_integration()
            print()
            await test_custom_mcp_integration()

            print("\n🎉 All MCP integration tests passed!")

        except Exception as e:
            print(f"\n❌ Test failed: {e}")
            raise

    asyncio.run(run_tests())
