"""A2A Protocol Validation Middleware.

This module provides validation middleware for A2A protocol requests and responses.
Ensures compliance with JSON-RPC 2.0 and A2A protocol specifications.
"""

import json
import logging
from typing import Any, ClassVar
from uuid import UUID

from fastapi import HTTPException, Request, status
from pydantic import BaseModel, Field, ValidationError

try:
    # Pydantic v2
    from pydantic import ConfigDict
except ImportError:  # pragma: no cover
    ConfigDict = dict  # type: ignore[misc]

logger = logging.getLogger(__name__)


class JSONRPCRequest(BaseModel):
    """JSON-RPC 2.0 request validation model."""

    jsonrpc: str = "2.0"
    method: str
    params: dict[str, Any] | None = None
    id: str | None = None


class A2AMessagePart(BaseModel):
    """A2A message part validation."""

    text: str


class A2AMessage(BaseModel):
    """A2A message validation."""

    role: str = "user"
    parts: list[A2AMessagePart]


class A2AMessageSendParams(BaseModel):
    """A2A message/send parameters validation."""

    message: A2AMessage
    context_id: str | None = Field(None, alias="contextId")
    metadata: dict[str, Any] | None = None
    # Allow population by field name or alias
    model_config = ConfigDict(populate_by_name=True)


class A2ATaskParams(BaseModel):
    """A2A task parameters validation."""

    id: str


class A2AValidationError(Exception):
    """A2A protocol validation error."""

    def __init__(self, message: str, error_code: str = "VALIDATION_ERROR"):
        self.message = message
        self.error_code = error_code
        super().__init__(message)


class A2AValidator:
    """A2A protocol validator."""

    SUPPORTED_METHODS: ClassVar[set[str]] = {
        "message/send",
        "message/stream",
        "tasks/get",
        "tasks/cancel",
        "agent/authenticatedExtendedCard",
    }

    @classmethod
    def validate_json_rpc_request(cls, data: dict[str, Any]) -> JSONRPCRequest:
        """Validate JSON-RPC 2.0 request format."""
        try:
            request = JSONRPCRequest(**data)

            # Check JSON-RPC version
            if request.jsonrpc != "2.0":
                raise A2AValidationError(
                    f"Unsupported JSON-RPC version: {request.jsonrpc}. Expected: 2.0",
                    "INVALID_VERSION",
                )

            # Check method is supported
            if request.method not in cls.SUPPORTED_METHODS:
                raise A2AValidationError(
                    f"Unsupported method: {request.method}. "
                    f"Supported: {list(cls.SUPPORTED_METHODS)}",
                    "METHOD_NOT_FOUND",
                )

            return request

        except ValidationError as e:
            raise A2AValidationError(
                f"Invalid JSON-RPC request format: {e}", "INVALID_REQUEST"
            ) from e

    @classmethod
    def validate_message_send_params(cls, params: dict[str, Any]) -> A2AMessageSendParams:
        """Validate message/send method parameters."""
        try:
            return A2AMessageSendParams(**params)
        except ValidationError as e:
            raise A2AValidationError(
                f"Invalid message/send parameters: {e}", "INVALID_PARAMS"
            ) from e

    @classmethod
    def validate_task_params(cls, params: dict[str, Any]) -> A2ATaskParams:
        """Validate task-related method parameters."""
        try:
            return A2ATaskParams(**params)
        except ValidationError as e:
            raise A2AValidationError(f"Invalid task parameters: {e}", "INVALID_PARAMS") from e

    @classmethod
    def validate_agent_id(cls, agent_id: str) -> UUID:
        """Validate agent ID format."""
        try:
            return UUID(agent_id)
        except ValueError:
            raise A2AValidationError(
                f"Invalid agent ID format: {agent_id}. Expected UUID format.", "INVALID_AGENT_ID"
            ) from None

    @classmethod
    def validate_request_content_type(cls, request: Request) -> None:
        """Validate request content type."""
        content_type = request.headers.get("content-type", "")

        if not content_type.startswith("application/json"):
            raise A2AValidationError(
                f"Invalid content type: {content_type}. Expected: application/json",
                "INVALID_CONTENT_TYPE",
            )

    @classmethod
    async def validate_a2a_request(cls, request: Request, agent_id: UUID) -> JSONRPCRequest:
        """Validate complete A2A request."""
        # Validate content type
        cls.validate_request_content_type(request)

        # Parse JSON body
        try:
            body = await request.json()
        except json.JSONDecodeError as e:
            raise A2AValidationError(f"Invalid JSON body: {e}", "INVALID_JSON") from e

        # Validate JSON-RPC format
        json_rpc_request = cls.validate_json_rpc_request(body)

        # Validate method-specific parameters
        if json_rpc_request.method in ["message/send", "message/stream"]:
            if json_rpc_request.params:
                cls.validate_message_send_params(json_rpc_request.params)

        elif json_rpc_request.method in ["tasks/get", "tasks/cancel"]:
            if json_rpc_request.params:
                cls.validate_task_params(json_rpc_request.params)

        return json_rpc_request


def create_a2a_error_response(request_id: str | None, error: A2AValidationError) -> dict[str, Any]:
    """Create A2A-compliant error response."""
    # Map validation errors to JSON-RPC error codes
    error_code_mapping = {
        "INVALID_REQUEST": -32600,
        "METHOD_NOT_FOUND": -32601,
        "INVALID_PARAMS": -32602,
        "INVALID_JSON": -32700,
        "VALIDATION_ERROR": -32000,
        "INVALID_CONTENT_TYPE": -32001,
        "INVALID_AGENT_ID": -32002,
        "INVALID_VERSION": -32003,
    }

    error_code = error_code_mapping.get(error.error_code, -32000)

    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "error": {
            "code": error_code,
            "message": error.message,
            "data": {"error_type": error.error_code, "protocol": "A2A", "version": "1.0.0"},
        },
    }


async def validate_a2a_middleware(request: Request, agent_id: UUID) -> dict[str, Any] | None:
    """A2A validation middleware."""
    try:
        # Skip validation for non-RPC endpoints
        if not request.url.path.endswith("/rpc"):
            return None

        # Validate A2A request
        await A2AValidator.validate_a2a_request(request, agent_id)
        return None

    except A2AValidationError as e:
        logger.warning(f"A2A validation failed: {e.message}")

        # Try to extract request ID from body
        request_id = None
        try:
            body = await request.json()
            request_id = body.get("id")
        except Exception as e:
            logger.debug(f"Could not extract request ID from request body: {e}")

        # Return error response
        error_response = create_a2a_error_response(request_id, e)

        # Convert to HTTP exception
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_response) from e


# Dependency for A2A validation
async def require_a2a_validation(request: Request, agent_id: UUID) -> None:
    """Dependency that requires A2A validation."""
    await validate_a2a_middleware(request, agent_id)
