"""
Native Adapter

This adapter handles internal agents that use our native chat format
without requiring protocol translation.
"""

from typing import Dict, Any, Optional, AsyncGenerator

from .base import AgentAdapter, ChatMessage, ChatResponse, AgentTask, AgentTaskResponse


class NativeAdapter(AgentAdapter):
    """Adapter for native internal agents"""
    
    def __init__(self, agent_config: Dict[str, Any]):
        super().__init__(agent_config)
        self.agent_instance = agent_config.get("instance")
    
    async def send_task(
        self, 
        task: AgentTask, 
        session_id: Optional[str] = None
    ) -> AgentTaskResponse:
        """Send task to native agent"""
        
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
        """Stream task response from native agent"""
        
        chat_message = ChatMessage(content=task.content, metadata=task.metadata)
        return self.stream_message(chat_message, session_id)
        
    async def send_message(
        self, 
        message: ChatMessage, 
        context_id: Optional[str] = None
    ) -> ChatResponse:
        """Send message to native agent"""
        
        if not self.agent_instance:
            raise ValueError("Native agent instance not provided")
        
        # Call agent directly
        response = await self.agent_instance.process_message(
            message.content,
            context_id=context_id,
            metadata=message.metadata
        )
        
        return ChatResponse(
            content=response.get("content", ""),
            metadata={
                "agent_id": self.agent_id,
                "protocol": "native",
                **response.get("metadata", {})
            },
            status=response.get("status", "completed")
        )
    
    def stream_message(
        self, 
        message: ChatMessage, 
        context_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Stream response from native agent"""
        
        return self._stream_message_impl(message, context_id)
    
    async def _stream_message_impl(
        self, 
        message: ChatMessage, 
        context_id: Optional[str] = None
    ) -> AsyncGenerator[str, None]:
        """Implementation of stream message"""
        
        if not self.agent_instance:
            raise ValueError("Native agent instance not provided")
        
        # Stream from agent directly
        async for chunk in self.agent_instance.stream_message(
            message.content,
            context_id=context_id,
            metadata=message.metadata
        ):
            yield chunk
    
    async def get_capabilities(self) -> Dict[str, Any]:
        """Get native agent capabilities"""
        
        if self.agent_instance and hasattr(self.agent_instance, 'get_capabilities'):
            return await self.agent_instance.get_capabilities()
        
        return {
            "name": self.agent_name,
            "protocol": "native",
            "capabilities": ["chat", "streaming"]
        }
    
    async def health_check(self) -> bool:
        """Check if native agent is available"""
        
        return self.agent_instance is not None 
    
    async def create_agent(self, agent_spec: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new native agent instance"""
        
        # For native agents, we would typically instantiate a new agent class
        # This is a placeholder implementation
        raise NotImplementedError("Native agent creation not implemented") 