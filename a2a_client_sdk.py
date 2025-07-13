#!/usr/bin/env python3
"""
A2A Protocol Client SDK

Simple Python SDK for testing A2A protocol implementation.
Provides methods for agent discovery and communication.
"""

import asyncio
import json
import logging
from typing import Any, Dict, List, Optional, AsyncGenerator
from uuid import UUID, uuid4
import aiohttp

logger = logging.getLogger(__name__)


class A2AError(Exception):
    """A2A protocol error."""
    def __init__(self, message: str, code: int = None, data: Any = None):
        self.message = message
        self.code = code
        self.data = data
        super().__init__(message)


class A2AMessage:
    """A2A message builder."""
    
    def __init__(self, text: str, role: str = "user"):
        self.text = text
        self.role = role
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "role": self.role,
            "parts": [{"text": self.text}]
        }


class A2AAgentCard:
    """A2A agent card."""
    
    def __init__(self, data: Dict[str, Any]):
        self.name = data.get("name")
        self.description = data.get("description")
        self.url = data.get("url")
        self.version = data.get("version")
        self.capabilities = data.get("capabilities", {})
        self.provider = data.get("provider", {})
        self.skills = data.get("skills", [])
        self._raw_data = data
    
    def __repr__(self):
        return f"A2AAgentCard(name='{self.name}', url='{self.url}')"
    
    def has_capability(self, capability: str) -> bool:
        """Check if agent has specific capability."""
        return self.capabilities.get(capability, False)
    
    def get_skill_by_id(self, skill_id: str) -> Optional[Dict[str, Any]]:
        """Get skill by ID."""
        for skill in self.skills:
            if skill.get("id") == skill_id:
                return skill
        return None


class A2AClient:
    """A2A protocol client."""
    
    def __init__(self, base_url: str, auth_token: Optional[str] = None, api_key: Optional[str] = None):
        self.base_url = base_url.rstrip("/")
        self.auth_token = auth_token
        self.api_key = api_key
        self.session: Optional[aiohttp.ClientSession] = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    def _get_headers(self) -> Dict[str, str]:
        """Get request headers with authentication."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "A2A-Python-SDK/1.0.0"
        }
        
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"
        
        if self.api_key:
            headers["X-API-Key"] = self.api_key
        
        return headers
    
    async def _make_request(self, method: str, url: str, **kwargs) -> Dict[str, Any]:
        """Make HTTP request with error handling."""
        if not self.session:
            raise A2AError("Client session not initialized. Use 'async with' syntax.")
        
        try:
            async with self.session.request(method, url, headers=self._get_headers(), **kwargs) as response:
                response_data = await response.json()
                
                if response.status >= 400:
                    raise A2AError(
                        f"HTTP {response.status}: {response_data}",
                        code=response.status,
                        data=response_data
                    )
                
                return response_data
                
        except aiohttp.ClientError as e:
            raise A2AError(f"Request failed: {e}")
        except json.JSONDecodeError as e:
            raise A2AError(f"Invalid JSON response: {e}")
    
    # Discovery Methods
    
    async def discover_default_agent(self) -> A2AAgentCard:
        """Discover default agent via well-known endpoint."""
        url = f"{self.base_url}/.well-known/agent.json"
        data = await self._make_request("GET", url)
        return A2AAgentCard(data)
    
    async def discover_agent_by_id(self, agent_id: UUID) -> A2AAgentCard:
        """Discover specific agent via well-known endpoint."""
        url = f"{self.base_url}/.well-known/agent.json?agent_id={agent_id}"
        data = await self._make_request("GET", url)
        return A2AAgentCard(data)
    
    async def discover_all_agents(self, limit: int = 10, offset: int = 0) -> List[A2AAgentCard]:
        """Discover all agents via well-known endpoint."""
        url = f"{self.base_url}/.well-known/agents.json?limit={limit}&offset={offset}"
        data = await self._make_request("GET", url)
        
        agents = []
        for agent_data in data.get("agents", []):
            agents.append(A2AAgentCard(agent_data))
        
        return agents
    
    async def get_agent_card(self, agent_id: UUID) -> A2AAgentCard:
        """Get agent card via agent-specific endpoint."""
        url = f"{self.base_url}/v1/agents/{agent_id}/card"
        data = await self._make_request("GET", url)
        return A2AAgentCard(data)
    
    async def get_a2a_info(self) -> Dict[str, Any]:
        """Get A2A protocol information."""
        url = f"{self.base_url}/.well-known/a2a-info.json"
        return await self._make_request("GET", url)
    
    # Communication Methods
    
    async def send_message(
        self,
        agent_id: UUID,
        message: A2AMessage,
        context_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Send message to agent via JSON-RPC."""
        url = f"{self.base_url}/v1/agents/{agent_id}/rpc"
        
        request_data = {
            "jsonrpc": "2.0",
            "method": "message/send",
            "params": {
                "message": message.to_dict(),
                "contextId": context_id or str(uuid4()),
                "metadata": metadata or {}
            },
            "id": str(uuid4())
        }
        
        return await self._make_request("POST", url, json=request_data)
    
    async def stream_message(
        self,
        agent_id: UUID,
        message: A2AMessage,
        context_id: Optional[str] = None
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream message to agent via Server-Sent Events."""
        url = f"{self.base_url}/v1/agents/{agent_id}/stream"
        
        request_data = {
            "method": "message/stream",
            "params": {
                "message": message.to_dict(),
                "contextId": context_id or str(uuid4())
            }
        }
        
        if not self.session:
            raise A2AError("Client session not initialized. Use 'async with' syntax.")
        
        try:
            async with self.session.post(
                url,
                headers=self._get_headers(),
                json=request_data
            ) as response:
                
                if response.status >= 400:
                    error_text = await response.text()
                    raise A2AError(f"Stream failed: HTTP {response.status}: {error_text}")
                
                # Parse Server-Sent Events
                async for line in response.content:
                    line = line.decode('utf-8').strip()
                    
                    if line.startswith('data: '):
                        try:
                            data = json.loads(line[6:])  # Remove 'data: ' prefix
                            yield data
                        except json.JSONDecodeError:
                            continue
                        
        except aiohttp.ClientError as e:
            raise A2AError(f"Stream request failed: {e}")
    
    async def get_task_status(self, agent_id: UUID, task_id: str) -> Dict[str, Any]:
        """Get task status via JSON-RPC."""
        url = f"{self.base_url}/v1/agents/{agent_id}/rpc"
        
        request_data = {
            "jsonrpc": "2.0",
            "method": "tasks/get",
            "params": {"id": task_id},
            "id": str(uuid4())
        }
        
        return await self._make_request("POST", url, json=request_data)
    
    async def cancel_task(self, agent_id: UUID, task_id: str) -> Dict[str, Any]:
        """Cancel task via JSON-RPC."""
        url = f"{self.base_url}/v1/agents/{agent_id}/rpc"
        
        request_data = {
            "jsonrpc": "2.0",
            "method": "tasks/cancel",
            "params": {"id": task_id},
            "id": str(uuid4())
        }
        
        return await self._make_request("POST", url, json=request_data)


# Example Usage
async def main():
    """Example usage of A2A client SDK."""
    
    # Initialize client
    async with A2AClient("http://localhost:8000", api_key="test_user_key") as client:
        
        print("🔍 Discovering agents...")
        
        # Discover default agent
        try:
            default_agent = await client.discover_default_agent()
            print(f"✅ Default agent: {default_agent}")
        except A2AError as e:
            print(f"❌ Discovery failed: {e}")
            return
        
        # Discover all agents
        try:
            all_agents = await client.discover_all_agents(limit=5)
            print(f"✅ Found {len(all_agents)} agents")
            for agent in all_agents:
                print(f"  - {agent.name}: {agent.url}")
        except A2AError as e:
            print(f"❌ Agent listing failed: {e}")
        
        # Get A2A protocol info
        try:
            a2a_info = await client.get_a2a_info()
            print(f"✅ A2A Protocol: {a2a_info.get('protocol')} v{a2a_info.get('version')}")
        except A2AError as e:
            print(f"❌ A2A info failed: {e}")
        
        # Test communication with first agent
        if all_agents:
            agent = all_agents[0]
            print(f"\n💬 Testing communication with {agent.name}...")
            
            # Extract agent ID from URL
            try:
                agent_id_str = agent.url.split("/agents/")[1].split("/")[0]
                agent_id = UUID(agent_id_str)
                
                # Send message
                message = A2AMessage("Hello, can you help me?")
                response = await client.send_message(agent_id, message)
                print(f"✅ Message sent: {response}")
                
                # Test streaming (if supported)
                if agent.has_capability("streaming"):
                    print("🔄 Testing streaming...")
                    stream_message = A2AMessage("Tell me a story")
                    
                    async for chunk in client.stream_message(agent_id, stream_message):
                        print(f"📦 Stream chunk: {chunk}")
                        
                        # Stop after a few chunks for demo
                        if chunk.get("type") == "completion":
                            break
                            
            except Exception as e:
                print(f"❌ Communication test failed: {e}")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())