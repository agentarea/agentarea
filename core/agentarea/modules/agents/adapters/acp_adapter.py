"""
ACP (Agent Communication Protocol) Adapter

This adapter enables communication with ACP-compliant agents from the BeeAI ecosystem
by translating between our internal chat format and the ACP protocol.
"""

import httpx
import uuid
from typing import Dict, Any, Optional, AsyncGenerator

from .base import AgentAdapter, ChatMessage, ChatResponse, AgentTask, AgentTaskResponse


class ACPAdapter(AgentAdapter):
    """Adapter for ACP protocol agents (BeeAI)"""
    
    def __init__(self, agent_config: Dict[str, Any]):
        super().__init__(agent_config)
        self.base_url = agent_config.get("endpoint")
        self.timeout = agent_config.get("timeout", 30)
    
    async def send_task(
        self, 
        task: AgentTask, 
        session_id: Optional[str] = None
    ) -> AgentTaskResponse:
        """Send task via ACP protocol"""
        
        # Convert task to chat message for backward compatibility
        chat_message = ChatMessage(content=task.content, metadata=task.metadata)
        chat_response = await self.send_message(chat_message, session_id)
        
        # Convert back to task response
        return AgentTaskResponse(
            content=chat_response.content,
            metadata=chat_response.metadata,
            status=chat_response.status
        )
    
    def stream_task(
        self, 
        task: AgentTask, 
        session_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Stream task response via ACP protocol"""
        
        chat_message = ChatMessage(content=task.content, metadata=task.metadata)
        return self.stream_message(chat_message, session_id)
        
    async def send_message(
        self, 
        message: ChatMessage, 
        context_id: Optional[str] = None
    ) -> ChatResponse:
        """Send message via ACP protocol"""
        
        # ACP message format
        acp_payload = {
            "message": message.content,
            "context": {
                "sessionId": context_id or str(uuid.uuid4()),
                "userId": message.metadata.get("user_id") if message.metadata else None
            }
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            response = await client.post(
                f"{self.base_url}/acp/message",
                json=acp_payload
            )
            response.raise_for_status()
            
            result = response.json()
            
            return ChatResponse(
                content=result.get("response", ""),
                metadata={
                    "session_id": result.get("sessionId"),
                    "agent_id": self.agent_id,
                    "protocol": "acp"
                },
                status="completed"
            )
    
    def stream_message(
        self, 
        message: ChatMessage, 
        context_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Stream response from ACP agent"""
        
        return self._stream_message_impl(message, context_id)
    
    async def _stream_message_impl(
        self, 
        message: ChatMessage, 
        context_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Implementation of stream message"""
        
        acp_payload = {
            "message": message.content,
            "context": {
                "sessionId": context_id or str(uuid.uuid4()),
                "userId": message.metadata.get("user_id") if message.metadata else None
            },
            "stream": True
        }
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream(
                "POST", 
                f"{self.base_url}/acp/stream",
                json=acp_payload
            ) as response:
                response.raise_for_status()
                
                async for chunk in response.aiter_text():
                    if chunk.strip():
                        yield chunk
    
    async def get_capabilities(self) -> Dict[str, Any]:
        """Get ACP agent capabilities"""
        
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                response = await client.get(f"{self.base_url}/acp/capabilities")
                response.raise_for_status()
                return response.json()
            except httpx.HTTPError:
                return {
                    "name": self.agent_name,
                    "protocol": "acp",
                    "capabilities": ["chat", "streaming"]
                }
    
    async def health_check(self) -> bool:
        """Check if ACP agent is available"""
        
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                response = await client.get(f"{self.base_url}/acp/health")
                return response.status_code == 200
        except:
            return False 
    
    async def create_agent(self, agent_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new agent on ACP platform (not typically supported)"""
        
        # ACP platforms typically don't support agent creation via API
        # This is a placeholder implementation
        raise NotImplementedError("ACP platforms don't typically support dynamic agent creation") 