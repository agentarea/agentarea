"""
Enhanced A2A (Agent-to-Agent) Protocol Adapter

This adapter combines our current A2A implementation with the official A2A SDK
for better protocol compliance and enhanced agent communication capabilities.
"""

import asyncio
import httpx
import uuid
import logging
from typing import Dict, Any, Optional, AsyncGenerator
from datetime import datetime, timezone

from .base import AgentAdapter, AgentTask, AgentTaskResponse

logger = logging.getLogger(__name__)


class EnhancedA2AAdapter(AgentAdapter):
    """Enhanced A2A protocol adapter with official SDK integration"""

    def __init__(self, agent_config: Dict[str, Any]):
        super().__init__(agent_config)
        self.base_url = agent_config.get("endpoint")
        self.timeout = agent_config.get("timeout", 30)
        self.api_key = agent_config.get("api_key")
        self.use_official_sdk = agent_config.get("use_official_sdk", False)

        # Initialize official A2A client if configured
        self.a2a_client = None
        if self.use_official_sdk:
            self._init_a2a_client()

    def _init_a2a_client(self):
        """Initialize the official A2A SDK client"""
        try:
            # Note: This will be implemented when a2a-sdk is installed
            # from a2a.sdk import A2AClient
            # self.a2a_client = A2AClient(
            #     endpoint=self.base_url,
            #     api_key=self.api_key
            # )
            logger.info("A2A SDK client initialization prepared (requires a2a-sdk installation)")
        except ImportError:
            logger.warning("A2A SDK not available, falling back to HTTP implementation")
            self.use_official_sdk = False

    async def send_task(
        self, task: AgentTask, session_id: Optional[str] = None
    ) -> AgentTaskResponse:
        """Send task to remote A2A agent"""

        if self.use_official_sdk and self.a2a_client:
            return await self._send_task_via_sdk(task, session_id)
        else:
            return await self._send_task_via_http(task, session_id)

    async def _send_task_via_sdk(
        self, task: AgentTask, session_id: Optional[str] = None
    ) -> AgentTaskResponse:
        """Send task using the official A2A SDK"""
        try:
            # This will be implemented when SDK is available
            # task_request = TaskRequest(
            #     id=str(uuid.uuid4()),
            #     message=Message(
            #         role="user",
            #         parts=[TextPart(text=task.content)]
            #     ),
            #     metadata={
            #         **(task.metadata or {}),
            #         "session_id": session_id,
            #         "task_type": task.task_type,
            #         "source": "agentarea"
            #     }
            # )
            #
            # response = await self.a2a_client.send_task(task_request)
            #
            # # Extract content from response
            # content = ""
            # if response.artifacts:
            #     for artifact in response.artifacts:
            #         if artifact.type == "text":
            #             content = artifact.content
            #             break
            #
            # return AgentTaskResponse(
            #     content=content,
            #     artifacts=response.artifacts,
            #     metadata={
            #         "task_id": response.task_id,
            #         "protocol": "a2a_sdk",
            #         "agent_endpoint": self.base_url
            #     },
            #     status=response.status
            # )

            # Fallback to HTTP for now
            logger.info("SDK method not yet implemented, using HTTP fallback")
            return await self._send_task_via_http(task, session_id)

        except Exception as e:
            logger.error(f"Error sending task via A2A SDK: {e}")
            # Fallback to HTTP implementation
            return await self._send_task_via_http(task, session_id)

    async def _send_task_via_http(
        self, task: AgentTask, session_id: Optional[str] = None
    ) -> AgentTaskResponse:
        """Send task using HTTP (our current implementation)"""

        # Enhanced A2A Task payload with better compliance
        task_payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/send",
            "params": {
                "message": {"role": "user", "parts": [{"text": task.content}]},
                "contextId": session_id or str(uuid.uuid4()),
                "metadata": {
                    **(task.metadata or {}),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "agentarea",
                    "task_type": task.task_type,
                    "protocol_version": "1.0",
                },
            },
        }

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgentArea/1.0 (A2A-compliant)",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Try A2A JSON-RPC endpoint first
            try:
                response = await client.post(
                    f"{self.base_url}/protocol/rpc", json=task_payload, headers=headers
                )
                response.raise_for_status()
                result = response.json()

                # Handle JSON-RPC response
                if result.get("error"):
                    raise Exception(f"A2A RPC Error: {result['error']}")

                task_result = result.get("result", {})

            except (httpx.HTTPError, KeyError):
                # Fallback to REST endpoint
                logger.info("JSON-RPC endpoint failed, trying REST fallback")
                rest_payload = {
                    "id": str(uuid.uuid4()),
                    "sessionId": session_id or str(uuid.uuid4()),
                    "message": task.content,
                    "type": task.task_type,
                    "context": task.context or {},
                    "metadata": task_payload["params"]["metadata"],
                }

                response = await client.post(
                    f"{self.base_url}/tasks", json=rest_payload, headers=headers
                )
                response.raise_for_status()
                task_result = response.json()

            # Poll for completion if needed
            if task_result.get("status") == "working":
                task_result = await self._poll_task_completion(client, task_result["id"], headers)

            # Extract response from artifacts with enhanced processing
            content = ""
            artifacts = []

            if task_result.get("artifacts"):
                artifacts = task_result["artifacts"]
                # Get main content from artifacts
                for artifact in artifacts:
                    if artifact.get("type") == "text":
                        content = artifact.get("content", "")
                        break
            elif task_result.get("message"):
                # Handle direct message response
                content = task_result["message"]
            elif task_result.get("response"):
                # Handle response field
                content = task_result["response"]

            return AgentTaskResponse(
                content=content,
                artifacts=artifacts,
                metadata={
                    "task_id": task_result.get("id"),
                    "session_id": task_result.get("sessionId"),
                    "agent_endpoint": self.base_url,
                    "protocol": "enhanced_a2a",
                    "method": "json_rpc" if "jsonrpc" in task_payload else "rest",
                },
                status=task_result.get("status", "completed"),
            )

    async def get_capabilities(self) -> Dict[str, Any]:
        """Get remote A2A agent capabilities with enhanced discovery"""

        headers = {"User-Agent": "AgentArea/1.0 (A2A-compliant)"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            # Try multiple discovery methods
            discovery_methods = [
                # A2A agent card endpoint
                ("/.well-known/agent.json", "agent_card"),
                # JSON-RPC agent card method
                ("/protocol/rpc", "json_rpc_card"),
                # REST agent info
                ("/agent/info", "rest_info"),
                # Health check with capabilities
                ("/health", "health_check"),
            ]

            for endpoint, method in discovery_methods:
                try:
                    if method == "json_rpc_card":
                        # Try A2A JSON-RPC agent card method
                        rpc_payload = {
                            "jsonrpc": "2.0",
                            "id": str(uuid.uuid4()),
                            "method": "agent/authenticatedExtendedCard",
                            "params": {},
                        }
                        response = await client.post(
                            f"{self.base_url}{endpoint}", json=rpc_payload, headers=headers
                        )
                    else:
                        response = await client.get(f"{self.base_url}{endpoint}", headers=headers)

                    response.raise_for_status()
                    capabilities = response.json()

                    # Handle JSON-RPC response
                    if method == "json_rpc_card" and "result" in capabilities:
                        capabilities = capabilities["result"]

                    # Enhance capabilities with metadata
                    capabilities.update(
                        {
                            "is_remote": True,
                            "endpoint": self.base_url,
                            "discovery_method": method,
                            "protocol_compliance": "a2a_enhanced",
                        }
                    )

                    logger.info(f"Agent capabilities discovered via {method}")
                    return capabilities

                except httpx.HTTPError:
                    continue

            # Fallback to basic info
            return {
                "name": self.agent_name,
                "protocol": "enhanced_a2a",
                "is_remote": True,
                "endpoint": self.base_url,
                "capabilities": ["tasks", "streaming", "chat"],
                "discovery_method": "fallback",
            }

    async def health_check(self) -> bool:
        """Enhanced health check with A2A compliance verification"""

        try:
            headers = {"User-Agent": "AgentArea/1.0 (A2A-compliant)"}
            if self.api_key:
                headers["Authorization"] = f"Bearer {self.api_key}"

            async with httpx.AsyncClient(timeout=5) as client:
                # Try A2A-specific health endpoints
                health_endpoints = ["/health", "/protocol/health", "/.well-known/health"]

                for endpoint in health_endpoints:
                    try:
                        response = await client.get(f"{self.base_url}{endpoint}", headers=headers)
                        if response.status_code == 200:
                            health_data = response.json()
                            # Check for A2A protocol indicators
                            if any(key in health_data for key in ["protocol", "a2a", "agent"]):
                                logger.info(f"A2A agent healthy via {endpoint}")
                                return True
                    except:
                        continue

                return False
        except:
            return False

    async def _poll_task_completion(
        self,
        client: httpx.AsyncClient,
        task_id: str,
        headers: Dict[str, str],
        max_attempts: int = 30,
    ) -> Dict[str, Any]:
        """Poll task completion with enhanced A2A methods"""

        for attempt in range(max_attempts):
            try:
                # Try JSON-RPC task status first
                rpc_payload = {
                    "jsonrpc": "2.0",
                    "id": str(uuid.uuid4()),
                    "method": "tasks/get",
                    "params": {"id": task_id},
                }

                try:
                    response = await client.post(
                        f"{self.base_url}/protocol/rpc", json=rpc_payload, headers=headers
                    )
                    response.raise_for_status()
                    result = response.json()

                    if result.get("error"):
                        raise Exception("RPC error")

                    task_data = result.get("result", {})

                except:
                    # Fallback to REST
                    response = await client.get(f"{self.base_url}/tasks/{task_id}", headers=headers)
                    response.raise_for_status()
                    task_data = response.json()

                # Check if task is complete
                status = task_data.get("status", "")
                if status in ["completed", "failed", "cancelled"]:
                    return task_data

                # Wait before next poll
                await asyncio.sleep(1)

            except Exception as e:
                logger.warning(f"Error polling task {task_id}: {e}")
                await asyncio.sleep(1)

        # Timeout
        return {"status": "timeout", "id": task_id}

    def stream_task(
        self, task: AgentTask, session_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Stream task response from remote A2A agent"""
        return self._stream_task_impl(task, session_id)

    async def _stream_task_impl(
        self, task: AgentTask, session_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Implementation of stream task with enhanced A2A support"""

        # Enhanced streaming payload
        stream_payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "message/stream",
            "params": {
                "message": {"role": "user", "parts": [{"text": task.content}]},
                "contextId": session_id or str(uuid.uuid4()),
                "metadata": {
                    **(task.metadata or {}),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                    "source": "agentarea",
                    "task_type": task.task_type,
                    "stream": True,
                },
            },
        }

        headers = {
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
            "User-Agent": "AgentArea/1.0 (A2A-compliant)",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # Try A2A JSON-RPC streaming
                async with client.stream(
                    "POST", f"{self.base_url}/protocol/rpc", json=stream_payload, headers=headers
                ) as response:
                    response.raise_for_status()

                    async for chunk in response.aiter_text():
                        if chunk.strip():
                            yield chunk

            except httpx.HTTPError:
                # Fallback to REST streaming
                rest_payload = {
                    "id": str(uuid.uuid4()),
                    "sessionId": session_id or str(uuid.uuid4()),
                    "message": task.content,
                    "type": task.task_type,
                    "stream": True,
                }

                async with client.stream(
                    "POST", f"{self.base_url}/tasks/stream", json=rest_payload, headers=headers
                ) as response:
                    response.raise_for_status()

                    async for chunk in response.aiter_text():
                        if chunk.strip():
                            yield chunk

    async def create_agent(self, agent_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new agent on remote A2A platform with enhanced capabilities"""

        headers = {
            "Content-Type": "application/json",
            "User-Agent": "AgentArea/1.0 (A2A-compliant)",
        }
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        # Enhanced A2A agent creation payload
        creation_payload = {
            "jsonrpc": "2.0",
            "id": str(uuid.uuid4()),
            "method": "agent/create",
            "params": {
                "name": agent_spec.get("name"),
                "description": agent_spec.get("description"),
                "capabilities": agent_spec.get("capabilities", []),
                "model": agent_spec.get("model"),
                "instructions": agent_spec.get("instructions"),
                "metadata": {
                    **(agent_spec.get("metadata", {})),
                    "created_by": "agentarea",
                    "protocol_version": "1.0",
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            },
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                # Try A2A JSON-RPC agent creation
                response = await client.post(
                    f"{self.base_url}/protocol/rpc", json=creation_payload, headers=headers
                )
                response.raise_for_status()
                result = response.json()

                if result.get("error"):
                    raise Exception(f"A2A RPC Error: {result['error']}")

                agent_info = result.get("result", {})

            except httpx.HTTPError:
                # Fallback to REST endpoint
                rest_payload = creation_payload["params"]
                response = await client.post(
                    f"{self.base_url}/agents", json=rest_payload, headers=headers
                )
                response.raise_for_status()
                agent_info = response.json()

            return {
                "id": agent_info.get("id"),
                "name": agent_info.get("name"),
                "endpoint": f"{self.base_url}/agents/{agent_info.get('id')}",
                "protocol": "enhanced_a2a",
                "is_remote": True,
                "created_at": agent_info.get("created_at"),
                "capabilities": agent_info.get("capabilities", []),
                "metadata": agent_info.get("metadata", {}),
            }


# Factory function for creating the right adapter
def create_a2a_adapter(agent_config: Dict[str, Any]) -> AgentAdapter:
    """Create the appropriate A2A adapter based on configuration"""

    if agent_config.get("enhanced_a2a", True):
        return EnhancedA2AAdapter(agent_config)
    else:
        # Use original adapter
        from .a2a_adapter import A2AAdapter

        return A2AAdapter(agent_config)
