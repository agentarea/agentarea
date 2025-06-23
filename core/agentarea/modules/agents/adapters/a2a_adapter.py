"""
A2A (Agent-to-Agent) Protocol Adapter

This adapter enables communication with remote A2A-compliant agents by translating
between our internal task format and the A2A Task protocol.

Supports both existing remote agents and creating new agent instances on A2A platforms.
"""

import asyncio
import httpx
import uuid
from typing import Dict, Any, Optional, AsyncGenerator, List
from datetime import datetime, timezone

from .base import AgentAdapter, AgentTask, AgentTaskResponse


class A2AAdapter(AgentAdapter):
    """Adapter for remote A2A protocol agents"""

    def __init__(self, agent_config: Dict[str, Any]):
        super().__init__(agent_config)
        self.base_url = agent_config.get("endpoint")
        self.timeout = agent_config.get("timeout", 30)
        self.api_key = agent_config.get("api_key")

    async def send_task(
        self, task: AgentTask, session_id: Optional[str] = None
    ) -> AgentTaskResponse:
        """Send task to remote A2A agent"""

        # Create A2A Task payload
        task_payload = {
            "id": str(uuid.uuid4()),
            "sessionId": session_id or str(uuid.uuid4()),
            "message": task.content,
            "type": task.task_type,
            "context": task.context or {},
            "metadata": {
                **(task.metadata or {}),
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "source": "agentarea",
            },
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Send task to remote A2A agent
            response = await client.post(
                f"{self.base_url}/tasks", json=task_payload, headers=headers
            )
            response.raise_for_status()

            task_result = response.json()

            # Poll for completion if needed
            if task_result.get("status") == "working":
                task_result = await self._poll_task_completion(client, task_result["id"], headers)

            # Extract response from artifacts
            content = ""
            artifacts = []

            if task_result.get("artifacts"):
                artifacts = task_result["artifacts"]
                # Get main content from first text artifact
                for artifact in artifacts:
                    if artifact.get("type") == "text":
                        content = artifact.get("content", "")
                        break

            return AgentTaskResponse(
                content=content,
                artifacts=artifacts,
                metadata={
                    "task_id": task_result["id"],
                    "session_id": task_result.get("sessionId"),
                    "agent_endpoint": self.base_url,
                    "protocol": "a2a",
                },
                status=task_result.get("status", "completed"),
            )

    def stream_task(
        self, task: AgentTask, session_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Stream task response from remote A2A agent"""

        return self._stream_task_impl(task, session_id)

    async def _stream_task_impl(
        self, task: AgentTask, session_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Implementation of stream task"""

        task_payload = {
            "id": str(uuid.uuid4()),
            "sessionId": session_id or str(uuid.uuid4()),
            "message": task.content,
            "type": task.task_type,
            "context": task.context or {},
            "stream": True,
        }

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", f"{self.base_url}/tasks/stream", json=task_payload, headers=headers
            ) as response:
                response.raise_for_status()

                async for chunk in response.aiter_text():
                    if chunk.strip():
                        yield chunk

    async def get_capabilities(self) -> Dict[str, Any]:
        """Get remote A2A agent capabilities"""

        headers = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Try to get agent card
            try:
                response = await client.get(
                    f"{self.base_url}/.well-known/agent.json", headers=headers
                )
                response.raise_for_status()
                capabilities = response.json()
                capabilities["is_remote"] = True
                capabilities["endpoint"] = self.base_url
                return capabilities
            except httpx.HTTPError:
                # Fallback to basic info
                return {
                    "name": self.agent_name,
                    "protocol": "a2a",
                    "is_remote": True,
                    "endpoint": self.base_url,
                    "capabilities": ["tasks", "streaming", "chat"],
                }

    async def health_check(self) -> bool:
        """Check if remote A2A agent is available"""

        try:
            headers = {}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/health", headers=headers)
                return response.status_code == 200
        except:
            return False

    async def create_agent(self, agent_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new agent on remote A2A platform"""

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # A2A agent creation payload
        creation_payload = {
            "name": agent_spec.get("name"),
            "description": agent_spec.get("description"),
            "capabilities": agent_spec.get("capabilities", []),
            "model": agent_spec.get("model"),
            "instructions": agent_spec.get("instructions"),
            "metadata": agent_spec.get("metadata", {}),
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/agents", json=creation_payload, headers=headers
            )
            response.raise_for_status()

            agent_info = response.json()

            return {
                "id": agent_info.get("id"),
                "name": agent_info.get("name"),
                "endpoint": f"{self.base_url}/agents/{agent_info.get('id')}",
                "protocol": "a2a",
                "is_remote": True,
                "created_at": agent_info.get("created_at"),
                "capabilities": agent_info.get("capabilities", []),
            }

    async def _poll_task_completion(
        self,
        client: httpx.AsyncClient,
        task_id: str,
        headers: Dict[str, str],
        max_attempts: int = 30,
    ) -> Dict[str, Any]:
        """Poll remote A2A task until completion"""

        for _ in range(max_attempts):
            response = await client.get(f"{self.base_url}/tasks/{task_id}", headers=headers)
            response.raise_for_status()

            task_result = response.json()
            status = task_result.get("status")

            if status in ["completed", "failed", "cancelled"]:
                return task_result

            await asyncio.sleep(1)

        raise TimeoutError(f"Task {task_id} did not complete within timeout")
