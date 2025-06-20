"""
Mock Adapter for Testing

This adapter simulates agent responses without requiring actual HTTP requests.
Perfect for testing A2A protocol compliance and chat functionality.
"""

import asyncio
import uuid
from typing import Dict, Any, Optional, AsyncGenerator

from .base import AgentAdapter, AgentTask, AgentTaskResponse


class MockAdapter(AgentAdapter):
    """Mock adapter that simulates agent responses for testing"""
    
    def __init__(self, agent_config: Dict[str, Any]):
        super().__init__(agent_config)
        self.agent_name = agent_config.get("name", "Mock Agent")
        self.agent_id = agent_config.get("id", "mock-agent")
        
    async def send_task(
        self, 
        task: AgentTask, 
        session_id: Optional[str] = None
    ) -> AgentTaskResponse:
        """Simulate sending a task to an agent"""
        
        # Simulate processing delay
        await asyncio.sleep(0.1)
        
        # Generate mock response based on task type
        if task.task_type == "message":
            response_content = f"Mock response to: {task.content[:50]}... (from {self.agent_name})"
        elif task.task_type == "voice":
            response_content = f"Voice command processed: {task.content}"
        elif task.task_type == "action":
            response_content = f"Action executed: {task.content}"
        elif task.task_type == "query":
            response_content = f"Query result: {task.content}"
        else:
            response_content = f"Task processed: {task.content}"
        
        return AgentTaskResponse(
            content=response_content,
            status="completed",
            artifacts=[{
                "type": "text",
                "content": response_content,
                "metadata": {"generated_by": self.agent_name}
            }],
            metadata={
                "agent_id": self.agent_id,
                "agent_name": self.agent_name,
                "task_type": task.task_type,
                "session_id": session_id,
                "processing_time": "0.1s"
            }
        )
    
    async def stream_task(
        self, 
        task: AgentTask, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Simulate streaming response from an agent"""
        
        # Generate streaming response
        response_parts = [
            f"Streaming response from {self.agent_name}:\n",
            f"Processing your {task.task_type}: ",
            f"{task.content[:30]}...\n",
            "Analysis complete. ",
            "Here's my response: ",
            f"Mock streaming content for '{task.content[:20]}...'\n",
            "Stream completed."
        ]
        
        for part in response_parts:
            await asyncio.sleep(0.05)  # Simulate streaming delay
            yield part
    
    async def create_agent(self, agent_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Simulate creating a new agent"""
        
        agent_id = f"mock-{uuid.uuid4().hex[:8]}"
        
        return {
            "id": agent_id,
            "name": agent_spec.get("name", "New Mock Agent"),
            "description": agent_spec.get("description", "A mock agent for testing"),
            "protocol": "mock",
            "endpoint": f"mock://{agent_id}",
            "capabilities": agent_spec.get("capabilities", ["text", "streaming"]),
            "is_remote": False,
            "created_at": "2024-01-01T00:00:00Z"
        }
    
    def get_agent_info(self) -> Dict[str, Any]:
        """Get information about this mock agent"""
        return {
            "id": self.agent_id,
            "name": self.agent_name,
            "protocol": "mock",
            "status": "active",
            "capabilities": ["text", "streaming", "voice", "action", "query"],
            "description": "Mock agent for A2A protocol testing"
        }
    
    async def get_capabilities(self) -> Dict[str, Any]:
        """Get agent capabilities"""
        return {
            "text": True,
            "streaming": True,
            "voice": True,
            "action": True,
            "query": True,
            "multimodal": False
        }
    
    async def health_check(self) -> bool:
        """Check if the mock agent is healthy"""
        return True 