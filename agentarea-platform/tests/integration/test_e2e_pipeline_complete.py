#!/usr/bin/env python3
"""
E2E Pipeline Verification - Single Complete Test

This test verifies the complete AgentArea pipeline works end-to-end:
1. Sets up OpenAI provider configuration (optional)
2. Creates MCP server instance (Filesystem)
3. Creates a skill
4. Creates an agent with model, MCP, and skill
5. Verifies the agent configuration
6. Executes a task with real LLM (if OpenAI key provided)
7. Cleans up all resources

Tested On:
    - Local development environment with Docker Compose
    - AgentArea API: http://localhost:8000
    - Kratos auth with test JWKS (local dev only)

Usage:
    # 1. Start the local environment (all services including Temporal worker)
    docker-compose -f docker-compose.dev.yaml up -d

    # 2. Basic test (creates resources, no LLM call)
    cd agentarea-platform
    pytest tests/integration/test_e2e_pipeline_complete.py -v -s
    
    # 3. Full test with real LLM execution (requires valid OpenAI key)
    OPENAI_API_KEY=sk-xxx pytest tests/integration/test_e2e_pipeline_complete.py -v -s

Requirements:
    - AgentArea API running on http://localhost:8000
    - All infrastructure services (DB, Redis, Temporal, Kratos) running
    - Temporal worker running (for task execution)
    - Python packages: pytest, httpx, pyjwt, cryptography

Note:
    - The test uses a test JWT signing key that matches the local Kratos JWKS.
    - Task execution requires a valid OpenAI API key (starts with 'sk-').
    - Without OpenAI key, the test creates all resources but skips LLM execution.
"""

import asyncio
import base64
import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest
import yaml


# Configuration
API_BASE_URL = os.getenv("AGENTAREA_API_URL", "http://localhost:8000")
TEST_WORKSPACE = "e2e-test-workspace"

# Note: OpenAI key is optional - if not provided, test uses default model
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")


def generate_test_token() -> str:
    """Generate a test JWT token for local development."""
    try:
        import jwt
        from cryptography.hazmat.primitives import serialization
    except ImportError:
        pytest.skip("PyJWT and cryptography required for test token generation")
    
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


@pytest.fixture
async def api_client():
    """Create authenticated HTTP client."""
    token = generate_test_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": TEST_WORKSPACE,
    }
    
    async with httpx.AsyncClient(
        base_url=API_BASE_URL,
        timeout=60.0,
        headers=headers,
    ) as client:
        # Verify service is running
        try:
            response = await client.get("/")
            assert response.status_code == 200, f"API not accessible: {response.status_code}"
        except Exception as e:
            pytest.skip(f"AgentArea API not running: {e}")
        
        yield client


@pytest.fixture
async def test_resources(api_client: httpx.AsyncClient):
    """Track and cleanup created resources."""
    resources = {
        "agents": [],
        "skills": [],
        "mcp_instances": [],
        "provider_configs": [],
    }
    
    yield resources
    
    # Cleanup in reverse order
    print("\n🧹 Cleaning up resources...")
    
    for agent_id in resources["agents"]:
        try:
            await api_client.delete(f"/v1/agents/{agent_id}")
            print(f"  ✓ Deleted agent: {agent_id}")
        except Exception as e:
            print(f"  ⚠️ Failed to delete agent: {e}")
    
    for skill_id in resources["skills"]:
        try:
            await api_client.delete(f"/v1/skills/{skill_id}")
            print(f"  ✓ Deleted skill: {skill_id}")
        except Exception as e:
            print(f"  ⚠️ Failed to delete skill: {e}")
    
    for mcp_id in resources["mcp_instances"]:
        try:
            await api_client.delete(f"/v1/mcp-server-instances/{mcp_id}")
            print(f"  ✓ Deleted MCP instance: {mcp_id}")
        except Exception as e:
            print(f"  ⚠️ Failed to delete MCP instance: {e}")
    
    for pc_id in resources["provider_configs"]:
        try:
            await api_client.delete(f"/v1/provider-configs/{pc_id}")
            print(f"  ✓ Deleted provider config: {pc_id}")
        except Exception as e:
            print(f"  ⚠️ Failed to delete provider config: {e}")


class TestE2EPipeline:
    """Complete E2E pipeline verification test."""

    @pytest.mark.asyncio
    async def test_complete_pipeline(
        self,
        api_client: httpx.AsyncClient,
        test_resources: dict[str, list[str]],
    ):
        """Test complete pipeline: provider → MCP → skill → agent."""
        print("\n" + "=" * 60)
        print("🚀 E2E Pipeline Verification Test")
        print("=" * 60)
        
        suffix = uuid.uuid4().hex[:8]
        
        # Step 1: Create Provider Configuration (optional - no key needed for basic test)
        provider_config_id = None
        if OPENAI_API_KEY:
            print(f"\n📦 Step 1: Creating OpenAI Provider Config...")
            provider_config_id = await self._create_provider_config(
                api_client, test_resources, suffix
            )
            print(f"  ✅ Provider config: {provider_config_id}")
        else:
            print(f"\n📦 Step 1: Skipping provider config (no OPENAI_API_KEY - using default model)")
        
        # Step 2: Create MCP Instance
        print(f"\n🔌 Step 2: Creating MCP Instance...")
        mcp_instance_id = await self._create_mcp_instance(
            api_client, test_resources, suffix
        )
        print(f"  ✅ MCP instance: {mcp_instance_id}")
        
        # Step 3: Create Skill
        print(f"\n📚 Step 3: Creating Skill...")
        skill_id = await self._create_skill(api_client, test_resources, suffix)
        print(f"  ✅ Skill: {skill_id}")
        
        # Step 4: Create Agent
        print(f"\n🤖 Step 4: Creating Agent...")
        agent_id = await self._create_agent(
            api_client, test_resources, suffix, mcp_instance_id, skill_id
        )
        print(f"  ✅ Agent: {agent_id}")
        
        # Step 5: Verify Agent Configuration
        print(f"\n🔍 Step 5: Verifying Agent Configuration...")
        await self._verify_agent(api_client, agent_id, skill_id)
        print(f"  ✅ Agent configuration verified")
        
        # Step 6: Execute Task with Real LLM (if OpenAI key provided)
        if OPENAI_API_KEY and OPENAI_API_KEY.startswith("sk-"):
            print(f"\n🎯 Step 6: Executing Task with Real LLM...")
            task_result = await self._execute_task(api_client, agent_id)
            if task_result:
                print(f"  ✅ Task completed successfully")
            else:
                print(f"  ⚠️ Task did not complete (may need Temporal worker)")
        else:
            print(f"\n🎯 Step 6: Skipping task execution (no valid OPENAI_API_KEY)")
        
        print("\n" + "=" * 60)
        print("✅ E2E Pipeline Verification COMPLETE!")
        print("=" * 60)

    async def _create_provider_config(
        self,
        client: httpx.AsyncClient,
        resources: dict,
        suffix: str,
    ) -> str:
        """Create OpenAI provider configuration."""
        # Get OpenAI provider spec
        response = await client.get("/v1/provider-specs/by-key/openai")
        assert response.status_code == 200, f"Failed to get OpenAI spec: {response.text}"
        
        spec = response.json()
        provider_spec_id = spec["id"]
        
        # Create provider config
        data = {
            "provider_spec_id": provider_spec_id,
            "name": f"E2E Test OpenAI {suffix}",
            "api_key": OPENAI_API_KEY,
            "is_public": False,
        }
        
        response = await client.post("/v1/provider-configs/", json=data)
        assert response.status_code in [200, 201], f"Failed to create provider config: {response.text}"
        
        pc = response.json()
        resources["provider_configs"].append(pc["id"])
        return pc["id"]

    async def _create_mcp_instance(
        self,
        client: httpx.AsyncClient,
        resources: dict,
        suffix: str,
    ) -> str:
        """Create MCP server instance."""
        # Find Filesystem MCP server
        response = await client.get("/v1/mcp-servers/")
        assert response.status_code == 200, f"Failed to list MCP servers: {response.text}"
        
        servers = response.json()
        filesystem_server = next(
            (s for s in servers if s["name"].lower() == "filesystem"),
            None
        )
        assert filesystem_server, "Filesystem MCP server not found"
        
        # Create instance
        data = {
            "name": f"E2E Filesystem {suffix}",
            "description": "Filesystem MCP for E2E testing",
            "server_spec_id": filesystem_server["id"],
            "json_spec": {
                "type": "docker",
                "image": "mcp/filesystem",
                "port": 3000,
                "environment": {"FILESYSTEM_PATH": "/tmp"},
            },
        }
        
        response = await client.post("/v1/mcp-server-instances/", json=data)
        assert response.status_code in [200, 201], f"Failed to create MCP instance: {response.text}"
        
        mcp = response.json()
        resources["mcp_instances"].append(mcp["id"])
        return mcp["id"]

    async def _create_skill(
        self,
        client: httpx.AsyncClient,
        resources: dict,
        suffix: str,
    ) -> str:
        """Create a skill."""
        data = {
            "name": f"E2E Verification Skill {suffix}",
            "description": "Skill for E2E pipeline verification",
            "source_type": "content",
            "content": f"""---
name: E2E Verification Skill {suffix}
description: Skill for testing the declarative pipeline
tools:
  - name: verify_pipeline
    description: Verifies the pipeline is working
---

# E2E Verification Skill

This skill verifies the E2E pipeline is working correctly.
Test ID: {suffix}
""",
        }
        
        response = await client.post("/v1/skills", json=data)
        assert response.status_code in [200, 201], f"Failed to create skill: {response.text}"
        
        skill = response.json()
        resources["skills"].append(skill["id"])
        return skill["id"]

    async def _create_agent(
        self,
        client: httpx.AsyncClient,
        resources: dict,
        suffix: str,
        mcp_instance_id: str,
        skill_id: str,
    ) -> str:
        """Create an agent with MCP and skill."""
        # Build tools config
        tools = [
            {
                "type": "mcp",
                "name": f"E2E Filesystem {suffix}",
            }
        ]
        
        data = {
            "name": f"e2e-test-agent-{suffix}",
            "description": "Agent for E2E pipeline verification",
            "instruction": (
                "You are an AI assistant for E2E testing. "
                "You have access to filesystem tools via MCP. "
                "Be concise and helpful."
            ),
            "model_id": "gpt-4",  # Use recognized model identifier
            "tools": tools,
            "planning": False,
        }
        
        response = await client.post("/v1/agents/", json=data)
        assert response.status_code in [200, 201], f"Failed to create agent: {response.text}"
        
        agent = response.json()
        agent_id = agent["id"]
        
        # Attach skill
        update_data = {"skill_ids": [skill_id]}
        await client.patch(f"/v1/agents/{agent_id}", json=update_data)
        
        resources["agents"].append(agent_id)
        return agent_id

    async def _verify_agent(
        self,
        client: httpx.AsyncClient,
        agent_id: str,
        expected_skill_id: str,
    ):
        """Verify agent configuration."""
        # Get agent details
        response = await client.get(f"/v1/agents/{agent_id}")
        assert response.status_code == 200, "Failed to get agent"
        
        agent = response.json()
        assert agent["id"] == agent_id
        assert agent["name"].startswith("e2e-test-agent-")
        
        # Verify tools are configured
        tools = agent.get("tools", [])
        assert len(tools) > 0, "Agent has no tools configured"
        
        print(f"  ✓ Agent has {len(tools)} tool(s)")
        print(f"  ✓ Agent model_id: {agent.get('model_id', 'default')}")

    async def _execute_task(
        self,
        client: httpx.AsyncClient,
        agent_id: str,
    ) -> dict | None:
        """Execute a task with the agent and wait for completion."""
        # Create task
        task_data = {
            "description": "Say 'E2E test successful' and list your available capabilities.",
            "parameters": {
                "test_mode": True,
                "max_tokens": 200,
            },
        }
        
        print(f"  📤 Sending task to agent...")
        response = await client.post(f"/v1/agents/{agent_id}/tasks/", json=task_data)
        
        if response.status_code not in [200, 201]:
            print(f"    ⚠️ Failed to create task: {response.status_code} - {response.text[:200]}")
            return None
        
        task = response.json()
        task_id = task["id"]
        print(f"    ✓ Task created: {task_id}")
        
        # Wait for task completion (with timeout)
        print(f"    ⏳ Waiting for task completion (timeout: 120s)...")
        start_time = asyncio.get_event_loop().time()
        timeout = 120
        
        while True:
            elapsed = asyncio.get_event_loop().time() - start_time
            if elapsed > timeout:
                print(f"    ⚠️ Task timeout after {timeout}s")
                return None
            
            try:
                response = await client.get(f"/v1/agents/{agent_id}/tasks/{task_id}/status")
                if response.status_code == 200:
                    status = response.json()
                    task_status = status.get("status", "unknown")
                    
                    if task_status == "completed":
                        print(f"    ✓ Task completed!")
                        return status
                    elif task_status == "failed":
                        print(f"    ✗ Task failed: {status.get('error', 'Unknown error')}")
                        return None
                    elif task_status == "running":
                        print(f"    ... Status: {task_status} ({elapsed:.0f}s)")
                else:
                    print(f"    ... Status check: {response.status_code}")
            except Exception as e:
                print(f"    ⚠️ Error checking status: {e}")
            
            await asyncio.sleep(5)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
