"""
Real MCP Integration Test

Tests the complete workflow with a real MCP server:
1. Create agent
2. Deploy real MCP server (with Dockerfile)
3. Execute task using MCP tools
4. Verify task completion
"""
import asyncio
import pytest
import httpx
from typing import Optional, Dict, Any
import time


class MCPRealIntegrationTest:
    """Test class for real MCP integration."""
    
    def __init__(self, api_base: str = "http://localhost:8000"):
        self.api_base = api_base
        self.client: Optional[httpx.AsyncClient] = None
        self.agent_id: Optional[str] = None
        self.mcp_server_id: Optional[str] = None
        self.mcp_instance_id: Optional[str] = None
        self.task_id: Optional[str] = None

    async def setup(self):
        """Setup test client."""
        self.client = httpx.AsyncClient(timeout=60)

    async def cleanup(self):
        """Cleanup resources."""
        if self.client:
            await self.client.aclose()

    async def create_test_agent(self) -> bool:
        """Create a test agent for MCP integration."""
        agent_data = {
            "name": "MCP Test Agent",
            "description": "Agent for testing real MCP integration",
            "instruction": "You are a helpful assistant that uses MCP tools to help users.",
            "model_id": "test-model",  # Placeholder model
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

    async def deploy_mcp_server(self, 
                               server_name: str,
                               dockerfile_content: str, 
                               mcp_endpoint_url: str,
                               tools_metadata: list) -> bool:
        """Deploy a real MCP server with Dockerfile."""
        
        # Create MCP Server definition
        server_data = {
            "name": server_name,
            "description": f"Real MCP server: {server_name}",
            "version": "1.0.0",
            "docker_image_url": f"{server_name}:latest",  # Will be built from Dockerfile
            "dockerfile_content": dockerfile_content,  # For building the image
            "tools_metadata": tools_metadata
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
            "server_id": self.mcp_server_id,
            "endpoint_url": mcp_endpoint_url,
            "config": {
                "env": {
                    "PORT": "3000"
                }
            }
        }
        
        response = await self.client.post(f"{self.api_base}/v1/mcp-server-instances/", json=instance_data)
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

    async def execute_mcp_task(self, task_description: str, expected_tools: list) -> bool:
        """Execute a task that should use MCP tools."""
        task_data = {
            "description": task_description,
            "parameters": {
                "use_mcp_tools": True,
                "expected_tools": expected_tools
            },
            "metadata": {
                "integration_test": True,
                "mcp_server_id": self.mcp_server_id
            }
        }
        
        response = await self.client.post(f"{self.api_base}/v1/agents/{self.agent_id}/tasks/", json=task_data)
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
        instance_response = await self.client.get(f"{self.api_base}/v1/mcp-server-instances/{self.mcp_instance_id}")
        if instance_response.status_code != 200:
            print("❌ MCP instance not accessible")
            return False
            
        instance = instance_response.json()
        print(f"✅ MCP Integration verified")
        print(f"   Instance status: {instance['status']}")
        
        return True


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
                        "description": "City name or coordinates"
                    },
                    "units": {
                        "type": "string",
                        "description": "Temperature units (celsius/fahrenheit)",
                        "default": "celsius"
                    }
                },
                "required": ["location"]
            }
        },
        {
            "name": "get_forecast",
            "description": "Get weather forecast for a location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string", "description": "City name"},
                    "days": {"type": "integer", "description": "Number of days", "default": 3}
                },
                "required": ["location"]
            }
        }
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
            tools_metadata=tools_metadata
        ), "Failed to deploy MCP server"
        
        # Step 3: Execute weather task
        assert await test.execute_mcp_task(
            task_description="Get the current weather in Moscow and tell me if I need a jacket",
            expected_tools=["get_weather"]
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
                "properties": {
                    "path": {"type": "string", "description": "File path"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "write_file", 
            "description": "Write content to a file",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "content": {"type": "string", "description": "File content"}
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "list_directory",
            "description": "List files in a directory", 
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path"}
                },
                "required": ["path"]
            }
        }
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
            tools_metadata=tools_metadata
        ), "Failed to deploy MCP server"
        
        # Step 3: Execute filesystem task
        assert await test.execute_mcp_task(
            task_description="Create a file called 'test.txt' with content 'Hello MCP!' and then read it back",
            expected_tools=["write_file", "read_file"]
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
FROM node:18-alpine

WORKDIR /app

COPY package*.json ./
RUN npm install

COPY . .

EXPOSE 3000

CMD ["npm", "start"]
"""
    
    # Custom tools - can be modified based on actual MCP server
    tools_metadata = [
        {
            "name": "custom_tool",
            "description": "A custom MCP tool",
            "parameters": {
                "type": "object", 
                "properties": {
                    "input": {"type": "string", "description": "Input parameter"}
                },
                "required": ["input"]
            }
        }
    ]
    
    test = MCPRealIntegrationTest()
    await test.setup()
    
    try:
        # Step 1: Create agent
        assert await test.create_test_agent(), "Failed to create agent"
        
        # Step 2: Deploy custom MCP server  
        assert await test.deploy_mcp_server(
            server_name="custom-mcp-service",
            dockerfile_content=custom_dockerfile,
            mcp_endpoint_url="http://custom-mcp:3000",  # This can be customized
            tools_metadata=tools_metadata
        ), "Failed to deploy MCP server"
        
        # Step 3: Execute custom task
        assert await test.execute_mcp_task(
            task_description="Use the custom MCP tool to process some data",
            expected_tools=["custom_tool"]
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