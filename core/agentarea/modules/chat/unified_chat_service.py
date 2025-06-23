"""
Unified Task Service

This service provides a clean task interface that works with CopilotKit/Assistants-UI
while supporting multiple agent protocols through adapters. All interactions with agents
are treated as tasks, whether they're chat messages or complex operations.
"""

import uuid
from typing import Dict, Any, List, Optional, AsyncGenerator
from datetime import datetime, timezone

from agentarea.modules.agents.adapters.base import AgentAdapter, AgentTask, AgentTaskResponse
from agentarea.modules.agents.adapters.a2a_adapter import A2AAdapter
from agentarea.modules.agents.adapters.acp_adapter import ACPAdapter
from agentarea.modules.agents.adapters.native_adapter import NativeAdapter
from agentarea.modules.agents.adapters.mock_adapter import MockAdapter


class UnifiedTaskService:
    """Unified task service with protocol adapters for agent communication"""

    def __init__(self):
        self.adapters: Dict[str, AgentAdapter] = {}
        self.sessions: Dict[str, List[Dict[str, Any]]] = {}

    def register_agent(self, agent_id: str, agent_config: Dict[str, Any]) -> None:
        """Register an agent with appropriate adapter"""

        protocol = agent_config.get("protocol", "native")

        if protocol == "a2a":
            adapter = A2AAdapter(agent_config)
        elif protocol == "acp":
            adapter = ACPAdapter(agent_config)
        elif protocol == "native":
            adapter = NativeAdapter(agent_config)
        elif protocol == "mock":
            adapter = MockAdapter(agent_config)
        else:
            raise ValueError(f"Unsupported protocol: {protocol}")

        self.adapters[agent_id] = adapter

    async def create_agent(self, platform_id: str, agent_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new agent on a remote platform"""

        if platform_id not in self.adapters:
            raise ValueError(f"Platform {platform_id} not found")

        adapter = self.adapters[platform_id]

        # Create agent on remote platform
        agent_info = await adapter.create_agent(agent_spec)

        # Register the new agent locally
        new_agent_config = {
            "id": agent_info["id"],
            "name": agent_info["name"],
            "protocol": agent_info["protocol"],
            "endpoint": agent_info["endpoint"],
            "is_remote": agent_info.get("is_remote", True),
        }

        self.register_agent(agent_info["id"], new_agent_config)

        return agent_info

    async def send_task(
        self,
        content: str,
        agent_id: str,
        task_type: str = "message",
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Send a task to an agent - compatible with chat UIs"""

        if agent_id not in self.adapters:
            raise ValueError(f"Agent {agent_id} not found")

        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())

        # Create agent task
        task = AgentTask(
            content=content, task_type=task_type, context=context, metadata={"user_id": user_id}
        )

        # Send via adapter
        adapter = self.adapters[agent_id]
        response = await adapter.send_task(task, session_id)

        # Store task history
        self._store_interaction(
            session_id,
            {
                "id": str(uuid.uuid4()),
                "role": "user",
                "content": content,
                "task_type": task_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {"user_id": user_id},
            },
        )

        # Merge metadata safely
        response_metadata = {"agent_id": agent_id}
        if response.metadata:
            response_metadata.update(response.metadata)

        self._store_interaction(
            session_id,
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": response.content,
                "task_type": "response",
                "artifacts": response.artifacts,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": response_metadata,
            },
        )

        return {
            "id": str(uuid.uuid4()),
            "content": response.content,
            "role": "assistant",
            "session_id": session_id,
            "agent_id": agent_id,
            "task_type": task_type,
            "artifacts": response.artifacts,
            "status": response.status,
            "metadata": response.metadata,
        }

    async def stream_task(
        self,
        content: str,
        agent_id: str,
        task_type: str = "message",
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        user_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """Stream task response - compatible with streaming UIs"""

        if agent_id not in self.adapters:
            raise ValueError(f"Agent {agent_id} not found")

        # Generate session ID if not provided
        if not session_id:
            session_id = str(uuid.uuid4())

        # Create agent task
        task = AgentTask(
            content=content, task_type=task_type, context=context, metadata={"user_id": user_id}
        )

        # Store user task
        self._store_interaction(
            session_id,
            {
                "id": str(uuid.uuid4()),
                "role": "user",
                "content": content,
                "task_type": task_type,
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {"user_id": user_id},
            },
        )

        # Stream response
        adapter = self.adapters[agent_id]
        full_content = ""

        async for chunk in adapter.stream_task(task, session_id):
            full_content += chunk

            yield {
                "id": str(uuid.uuid4()),
                "content": chunk,
                "role": "assistant",
                "session_id": session_id,
                "agent_id": agent_id,
                "task_type": task_type,
                "type": "chunk",
            }

        # Store complete assistant response
        self._store_interaction(
            session_id,
            {
                "id": str(uuid.uuid4()),
                "role": "assistant",
                "content": full_content,
                "task_type": "response",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "metadata": {"agent_id": agent_id},
            },
        )

        # Send completion signal
        yield {
            "id": str(uuid.uuid4()),
            "session_id": session_id,
            "agent_id": agent_id,
            "task_type": task_type,
            "type": "complete",
        }

    async def get_session_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get session history - compatible with chat UIs"""

        return self.sessions.get(session_id, [])

    async def list_sessions(self, user_id: Optional[str] = None) -> List[Dict[str, Any]]:
        """List all sessions - compatible with chat UIs"""

        sessions: List[Dict[str, Any]] = []

        for session_id, interactions in self.sessions.items():
            if not interactions:
                continue

            # Filter by user if specified
            if user_id:
                user_interactions = [
                    i for i in interactions if i.get("metadata", {}).get("user_id") == user_id
                ]
                if not user_interactions:
                    continue

            # Get session summary
            first_interaction = interactions[0]
            last_interaction = interactions[-1]

            sessions.append(
                {
                    "id": session_id,
                    "title": first_interaction["content"][:50] + "..."
                    if len(first_interaction["content"]) > 50
                    else first_interaction["content"],
                    "last_message": last_interaction["content"],
                    "last_updated": last_interaction["timestamp"],
                    "interaction_count": len(interactions),
                    "task_types": list(set(i.get("task_type", "message") for i in interactions)),
                }
            )

        # Sort by last updated
        sessions.sort(key=lambda x: x["last_updated"], reverse=True)

        return sessions

    async def get_available_agents(self) -> List[Dict[str, Any]]:
        """Get list of available agents with capabilities"""

        agents: List[Dict[str, Any]] = []

        for agent_id, adapter in self.adapters.items():
            try:
                capabilities = await adapter.get_capabilities()
                health = await adapter.health_check()

                agents.append(
                    {
                        "id": agent_id,
                        "name": adapter.agent_name or agent_id,
                        "capabilities": capabilities,
                        "status": "online" if health else "offline",
                        "protocol": capabilities.get("protocol", "unknown"),
                        "is_remote": adapter.is_remote,
                        "endpoint": adapter.endpoint,
                    }
                )
            except Exception:
                agents.append(
                    {
                        "id": agent_id,
                        "name": adapter.agent_name or agent_id,
                        "status": "error",
                        "protocol": "unknown",
                        "is_remote": adapter.is_remote,
                        "endpoint": adapter.endpoint,
                    }
                )

        return agents

    async def get_platforms(self) -> List[Dict[str, Any]]:
        """Get list of available platforms for agent creation"""

        platforms = []

        for platform_id, adapter in self.adapters.items():
            if adapter.is_remote:
                try:
                    capabilities = await adapter.get_capabilities()
                    platforms.append(
                        {
                            "id": platform_id,
                            "name": adapter.agent_name or platform_id,
                            "endpoint": adapter.endpoint,
                            "protocol": capabilities.get("protocol", "unknown"),
                            "supports_creation": True,
                            "capabilities": capabilities,
                        }
                    )
                except Exception:
                    platforms.append(
                        {
                            "id": platform_id,
                            "name": adapter.agent_name or platform_id,
                            "endpoint": adapter.endpoint,
                            "supports_creation": False,
                            "status": "error",
                        }
                    )

        return platforms

    async def get_task_info(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get task information by ID"""
        # Search through all sessions for a task with this ID
        for session_id, interactions in self.sessions.items():
            for interaction in interactions:
                if interaction.get("id") == task_id:
                    return {
                        "id": task_id,
                        "session_id": session_id,
                        "content": interaction.get("content", ""),
                        "role": interaction.get("role", "unknown"),
                        "status": interaction.get("status", "completed"),
                        "timestamp": interaction.get("timestamp", ""),
                        "metadata": interaction.get("metadata", {}),
                    }
        return None

    async def cancel_task(self, task_id: str) -> bool:
        """Cancel a task by ID"""
        # For now, just return True as tasks are completed immediately
        # In a real implementation, this would communicate with the agent to cancel
        return True

    def _store_interaction(self, session_id: str, interaction: Dict[str, Any]) -> None:
        """Store interaction in session history"""

        if session_id not in self.sessions:
            self.sessions[session_id] = []

        self.sessions[session_id].append(interaction)
