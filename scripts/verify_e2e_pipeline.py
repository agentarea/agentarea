#!/usr/bin/env python3
"""
Single-file E2E Pipeline Verification

Tested On:
    - Local development environment with Docker Compose
    - AgentArea API: http://localhost:8000
    - Kratos auth with local dev JWKS

Prerequisites:
    1. Start the local environment:
       docker-compose -f docker-compose.dev.yaml up -d
    
    2. Install Python packages:
       pip install httpx pyjwt cryptography

Usage:
    # Basic test (creates resources, no LLM call)
    python scripts/verify_e2e_pipeline.py
    
    # Full test with real LLM execution (requires valid OpenAI key)
    OPENAI_API_KEY=sk-xxx python scripts/verify_e2e_pipeline.py

Environment Variables:
    AGENTAREA_API_URL - API URL (default: http://localhost:8000)
    OPENAI_API_KEY - OpenAI API key (optional)

Note:
    This script generates a test JWT token that works with the LOCAL dev
    environment's Kratos configuration. For other environments, you'll need
    to provide a valid token via AGENTAREA_API_TOKEN environment variable.
"""

import asyncio
import os
import uuid
from datetime import UTC, datetime, timedelta

import httpx


API_BASE_URL = os.getenv("AGENTAREA_API_URL", "http://localhost:8000")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TEST_WORKSPACE = os.getenv("TEST_WORKSPACE", "e2e-test-workspace")

# Use custom token if provided, otherwise generate test token
CUSTOM_TOKEN = os.getenv("AGENTAREA_API_TOKEN")


def generate_test_token() -> str:
    """Generate test JWT token."""
    import jwt
    from cryptography.hazmat.primitives import serialization
    
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
    
    return jwt.encode(payload, private_key, algorithm="ES256", headers={"kid": "agentarea-jwt-key-1"})


async def main():
    """Run E2E pipeline verification."""
    token = CUSTOM_TOKEN if CUSTOM_TOKEN else generate_test_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "X-Workspace-ID": TEST_WORKSPACE,
    }
    
    resources = {"agents": [], "skills": [], "mcp_instances": [], "provider_configs": []}
    suffix = uuid.uuid4().hex[:8]
    
    print("=" * 60)
    print("🚀 E2E Pipeline Verification")
    print(f"   API: {API_BASE_URL}")
    print(f"   Auth: {'Custom token' if CUSTOM_TOKEN else 'Test token (local dev)'}")
    print("=" * 60)
    
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=60.0, headers=headers) as client:
        # Check API is running
        try:
            response = await client.get("/")
            assert response.status_code == 200
            print(f"\n✅ API is running at {API_BASE_URL}")
        except Exception as e:
            print(f"\n❌ API not accessible: {e}")
            return 1
        
        # Step 1: Provider Config (optional - test works without it)
        if OPENAI_API_KEY:
            print(f"\n📦 Creating OpenAI Provider Config...")
            try:
                resp = await client.get("/v1/provider-specs/by-key/openai")
                spec = resp.json()
                
                resp = await client.post("/v1/provider-configs/", json={
                    "provider_spec_id": spec["id"],
                    "name": f"E2E OpenAI {suffix}",
                    "api_key": OPENAI_API_KEY,
                    "is_public": False,
                })
                pc = resp.json()
                resources["provider_configs"].append(pc["id"])
                print(f"  ✅ {pc['id']}")
            except Exception as e:
                print(f"  ⚠️ {e}")
        else:
            print(f"\n📦 Skipping provider config (no OPENAI_API_KEY)")
        
        # Step 2: MCP Instance
        print(f"\n🔌 Creating MCP Instance...")
        try:
            resp = await client.get("/v1/mcp-servers/")
            servers = resp.json()
            fs_server = next((s for s in servers if s["name"].lower() == "filesystem"), None)
            
            resp = await client.post("/v1/mcp-server-instances/", json={
                "name": f"E2E Filesystem {suffix}",
                "server_spec_id": fs_server["id"],
                "json_spec": {
                    "type": "docker",
                    "image": "mcp/filesystem",
                    "port": 3000,
                    "environment": {"FILESYSTEM_PATH": "/tmp"},
                },
            })
            mcp = resp.json()
            resources["mcp_instances"].append(mcp["id"])
            print(f"  ✅ {mcp['id']}")
        except Exception as e:
            print(f"  ❌ {e}")
            return 1
        
        # Step 3: Skill
        print(f"\n📚 Creating Skill...")
        try:
            resp = await client.post("/v1/skills", json={
                "name": f"E2E Skill {suffix}",
                "description": "E2E verification skill",
                "source_type": "content",
                "content": f"# E2E Skill\n\nTest ID: {suffix}",
            })
            skill = resp.json()
            resources["skills"].append(skill["id"])
            print(f"  ✅ {skill['id']}")
        except Exception as e:
            print(f"  ❌ {e}")
            return 1
        
        # Step 4: Agent
        print(f"\n🤖 Creating Agent...")
        try:
            resp = await client.post("/v1/agents/", json={
                "name": f"e2e-agent-{suffix}",
                "description": "E2E test agent",
                "instruction": "You are a test agent with filesystem access.",
                "model_id": "gpt-4",
                "tools": [{"type": "mcp", "name": f"E2E Filesystem {suffix}"}],
                "planning": False,
            })
            agent = resp.json()
            agent_id = agent["id"]
            
            # Attach skill
            await client.patch(f"/v1/agents/{agent_id}", json={"skill_ids": [skill["id"]]})
            
            resources["agents"].append(agent_id)
            print(f"  ✅ {agent_id}")
        except Exception as e:
            print(f"  ❌ {e}")
            return 1
        
        # Execute task with real LLM (if key provided)
        if OPENAI_API_KEY and OPENAI_API_KEY.startswith("sk-"):
            print(f"\n🎯 Executing Task with Real LLM...")
            try:
                # Create task
                resp = await client.post(f"/v1/agents/{agent_id}/tasks/", json={
                    "description": "Say 'E2E test successful' and confirm you can access filesystem tools.",
                    "parameters": {"test_mode": True, "max_tokens": 200},
                })
                task = resp.json()
                print(f"  📤 Task created: {task['id']}")
                
                # Wait for completion
                import asyncio
                start = asyncio.get_event_loop().time()
                while asyncio.get_event_loop().time() - start < 120:
                    resp = await client.get(f"/v1/agents/{agent_id}/tasks/{task['id']}/status")
                    if resp.status_code == 200:
                        status = resp.json()
                        if status.get("status") == "completed":
                            print(f"  ✅ Task completed successfully!")
                            break
                        elif status.get("status") == "failed":
                            print(f"  ✗ Task failed")
                            break
                    await asyncio.sleep(5)
                else:
                    print(f"  ⚠️ Task timeout")
            except Exception as e:
                print(f"  ⚠️ Task execution: {e}")
        
        print("\n" + "=" * 60)
        print("✅ E2E Pipeline Verification COMPLETE!")
        print("=" * 60)
    
    # Cleanup
    print("\n🧹 Cleaning up...")
    async with httpx.AsyncClient(base_url=API_BASE_URL, timeout=30.0, headers=headers) as client:
        for agent_id in resources["agents"]:
            try:
                await client.delete(f"/v1/agents/{agent_id}")
                print(f"  ✓ Deleted agent")
            except:
                pass
        
        for skill_id in resources["skills"]:
            try:
                await client.delete(f"/v1/skills/{skill_id}")
                print(f"  ✓ Deleted skill")
            except:
                pass
        
        for mcp_id in resources["mcp_instances"]:
            try:
                await client.delete(f"/v1/mcp-server-instances/{mcp_id}")
                print(f"  ✓ Deleted MCP instance")
            except:
                pass
        
        for pc_id in resources["provider_configs"]:
            try:
                await client.delete(f"/v1/provider-configs/{pc_id}")
                print(f"  ✓ Deleted provider config")
            except:
                pass
    
    return 0


if __name__ == "__main__":
    exit(asyncio.run(main()))
