"""Event serialization utilities for ADK-Temporal integration."""

import json
from typing import Any, Dict, List, Optional

from google.genai import types

from ...ag.adk.events.event import Event
from ...ag.adk.events.event_actions import EventActions


class EventSerializer:
    """Utility class to serialize/deserialize ADK Events for Temporal storage."""
    
    @staticmethod
    def event_to_dict(event: Event) -> Dict[str, Any]:
        """Convert ADK Event to dict for Temporal serialization.
        
        Args:
            event: ADK Event instance
            
        Returns:
            Dictionary representation suitable for Temporal serialization
        """
        # Use Pydantic's model_dump to get basic serialization
        event_dict = event.model_dump()
        
        # Handle special cases that might not serialize properly
        if event_dict.get("long_running_tool_ids"):
            # Convert set to list for JSON serialization
            event_dict["long_running_tool_ids"] = list(event_dict["long_running_tool_ids"])
        
        return event_dict
    
    @staticmethod
    def dict_to_event(event_dict: Dict[str, Any]) -> Event:
        """Convert dict back to ADK Event.
        
        Args:
            event_dict: Dictionary representation from Temporal
            
        Returns:
            ADK Event instance
        """
        # Handle special cases for deserialization
        if event_dict.get("long_running_tool_ids") and isinstance(event_dict["long_running_tool_ids"], list):
            # Convert list back to set
            event_dict["long_running_tool_ids"] = set(event_dict["long_running_tool_ids"])
        
        # Use Pydantic's parsing to reconstruct the Event
        return Event.model_validate(event_dict)
    
    @staticmethod
    def serialize_content(content: Optional[types.Content]) -> Optional[Dict[str, Any]]:
        """Serialize ADK Content object to dict.
        
        Args:
            content: ADK Content instance or None
            
        Returns:
            Dictionary representation or None
        """
        if content is None:
            return None
            
        # Convert to dict using Pydantic serialization
        return content.model_dump() if hasattr(content, 'model_dump') else dict(content)
    
    @staticmethod
    def deserialize_content(content_dict: Optional[Dict[str, Any]]) -> Optional[types.Content]:
        """Deserialize dict back to ADK Content object.
        
        Args:
            content_dict: Dictionary representation or None
            
        Returns:
            ADK Content instance or None
        """
        if content_dict is None:
            return None
            
        return types.Content.model_validate(content_dict)
    
    @staticmethod
    def serialize_events(events: List[Event]) -> List[Dict[str, Any]]:
        """Serialize a list of ADK Events to list of dicts.
        
        Args:
            events: List of ADK Event instances
            
        Returns:
            List of dictionary representations
        """
        return [EventSerializer.event_to_dict(event) for event in events]
    
    @staticmethod
    def deserialize_events(events_data: List[Dict[str, Any]]) -> List[Event]:
        """Deserialize list of dicts back to ADK Events.
        
        Args:
            events_data: List of dictionary representations
            
        Returns:
            List of ADK Event instances
        """
        return [EventSerializer.dict_to_event(event_dict) for event_dict in events_data]
    
    @staticmethod
    def extract_final_response(event: Event) -> Optional[str]:
        """Extract final response text from an ADK Event.
        
        Args:
            event: ADK Event instance
            
        Returns:
            String content if available, None otherwise
        """
        if not event.content or not event.content.parts:
            return None
            
        # Look for text parts in the content
        text_parts = []
        for part in event.content.parts:
            if part.text:
                text_parts.append(part.text)
        
        return "\n".join(text_parts) if text_parts else None
    
    @staticmethod
    def is_streaming_event(event: Event) -> bool:
        """Check if event is a streaming/partial event.
        
        Args:
            event: ADK Event instance
            
        Returns:
            True if event is partial/streaming, False otherwise
        """
        return getattr(event, 'partial', False)
    
    @staticmethod
    def has_function_calls(event: Event) -> bool:
        """Check if event contains function calls.
        
        Args:
            event: ADK Event instance
            
        Returns:
            True if event has function calls, False otherwise
        """
        return len(event.get_function_calls()) > 0
    
    @staticmethod
    def has_function_responses(event: Event) -> bool:
        """Check if event contains function responses.
        
        Args:
            event: ADK Event instance
            
        Returns:
            True if event has function responses, False otherwise
        """
        return len(event.get_function_responses()) > 0