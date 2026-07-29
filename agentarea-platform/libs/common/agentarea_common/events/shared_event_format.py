"""Framework-independent shared event format.

Based on CloudEvents specification for cross-language compatibility.
Used for communication between Python API and Go MCP Manager.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4


class SharedEventFormat:
    """Framework-independent event formatter for cross-language communication.

    Follows CloudEvents specification (https://cloudevents.io/):
    - specversion: CloudEvents spec version
    - type: Event type (reverse DNS notation)
    - source: Event origin
    - id: Unique event ID
    - time: ISO 8601 timestamp
    - datacontenttype: Content type of data
    - correlationid: Optional request correlation ID
    - data: Event payload

    Example:
        {
          "specversion": "1.0",
          "type": "com.agentarea.mcp.instance.created",
          "source": "agentarea-api",
          "id": "550e8400-e29b-41d4-a716-446655440000",
          "time": "2026-02-19T10:00:00Z",
          "datacontenttype": "application/json",
          "correlationid": "req-123",
          "data": {
            "instance_id": "uuid",
            "name": "my-mcp",
            "json_spec": {...}
          }
        }
    """

    SPEC_VERSION = "1.0"
    DEFAULT_SOURCE = "agentarea-api"
    DEFAULT_CONTENT_TYPE = "application/json"

    @classmethod
    def create_event(
        cls,
        event_type: str,
        data: dict[str, Any],
        source: str | None = None,
        correlation_id: str | None = None,
        event_id: str | UUID | None = None,
    ) -> dict[str, Any]:
        """Create a standardized event following CloudEvents format.

        Args:
            event_type: Event type in reverse DNS notation (e.g., "com.agentarea.mcp.instance.created")
            data: Event payload data
            source: Event origin service (default: "agentarea-api")
            correlation_id: Optional request correlation ID for tracing
            event_id: Optional event ID (generated if not provided)

        Returns:
            Event dictionary following CloudEvents spec
        """
        return {
            "specversion": cls.SPEC_VERSION,
            "type": event_type,
            "source": source or cls.DEFAULT_SOURCE,
            "id": str(event_id or uuid4()),
            "time": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "datacontenttype": cls.DEFAULT_CONTENT_TYPE,
            "correlationid": correlation_id,
            "data": data,
        }

    @classmethod
    def serialize(cls, event: dict[str, Any]) -> str:
        """Serialize event to JSON string.

        Args:
            event: Event dictionary

        Returns:
            JSON string representation
        """
        return json.dumps(event, default=cls._json_encoder)

    @classmethod
    def deserialize(cls, payload: str) -> dict[str, Any]:
        """Deserialize event from JSON string.

        Args:
            payload: JSON string

        Returns:
            Event dictionary
        """
        return json.loads(payload)

    @staticmethod
    def _json_encoder(obj: Any) -> Any:
        """Custom JSON encoder for non-standard types."""
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        raise TypeError(f"Object of type {type(obj)} is not JSON serializable")


# Convenience functions for common event types


def create_mcp_instance_created_event(
    instance_id: str,
    name: str,
    json_spec: dict[str, Any],
    server_spec_id: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Create an MCP instance created event."""
    return SharedEventFormat.create_event(
        event_type="com.agentarea.mcp.instance.created",
        data={
            "instance_id": instance_id,
            "name": name,
            "server_spec_id": server_spec_id,
            "json_spec": json_spec,
        },
        correlation_id=correlation_id,
    )


def create_mcp_instance_deleted_event(
    instance_id: str,
    name: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """Create an MCP instance deleted event."""
    return SharedEventFormat.create_event(
        event_type="com.agentarea.mcp.instance.deleted",
        data={
            "instance_id": instance_id,
            "name": name,
        },
        correlation_id=correlation_id,
    )


def get_channel_for_event_type(event_type: str) -> str:
    """Get Redis channel name for event type.

    Pattern: agentarea.events.{domain}.{action}
    Example: com.agentarea.mcp.instance.created -> agentarea.events.mcp.instance.created
    """
    # Convert reverse DNS to channel path
    parts = event_type.split(".")
    if len(parts) >= 2 and parts[0] == "com":
        return f"agentarea.events.{'.'.join(parts[2:])}"

    return f"agentarea.events.{event_type}"
