import re
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Any, Literal, Self
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    TypeAdapter,
    field_serializer,
    model_validator,
)


class TaskState(StrEnum):
    SUBMITTED = "submitted"
    WORKING = "working"
    INPUT_REQUIRED = "input-required"
    AUTH_REQUIRED = "auth-required"
    COMPLETED = "completed"
    CANCELED = "canceled"
    FAILED = "failed"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class TextPart(BaseModel):
    kind: Literal["text"] = "text"
    text: str
    metadata: dict[str, Any] | None = None


class FileContent(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str | None = Field(None, alias="filename")
    mime_type: str | None = Field(None, alias="mimeType")
    data: str | None = None
    uri: str | None = Field(None, alias="url")

    @model_validator(mode="after")
    def check_content(self) -> Self:
        if not (self.data or self.uri):
            raise ValueError("Either 'data' or 'uri' must be present in the file")
        if self.data and self.uri:
            raise ValueError("Only one of 'data' or 'uri' can be present")
        return self


class FilePart(BaseModel):
    kind: Literal["file"] = "file"
    file: FileContent
    metadata: dict[str, Any] | None = None


class DataPart(BaseModel):
    kind: Literal["data"] = "data"
    data: dict[str, Any]
    metadata: dict[str, Any] | None = None


Part = Annotated[TextPart | FilePart | DataPart, Field(discriminator="kind")]


class Message(BaseModel):
    role: Literal["user", "agent"]
    parts: list[Part]
    metadata: dict[str, Any] | None = None


class TaskStatus(BaseModel):
    state: TaskState
    message: Message | None = None
    timestamp: datetime = Field(default_factory=datetime.now)

    @field_serializer("timestamp")
    def serialize_dt(self, dt: datetime, _info):
        return dt.isoformat()


class Artifact(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    artifact_id: str | None = Field(None, alias="artifactId")
    name: str | None = None
    description: str | None = None
    parts: list[Part]
    metadata: dict[str, Any] | None = None
    index: int = 0
    append: bool | None = None
    last_chunk: bool | None = Field(None, alias="lastChunk")


class Task(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    context_id: str | None = Field(None, alias="contextId")
    status: TaskStatus
    artifacts: list[Artifact] | None = None
    history: list[Message] | None = None
    metadata: dict[str, Any] | None = None


class TaskStatusUpdateEvent(BaseModel):
    id: str
    status: TaskStatus
    final: bool = False
    metadata: dict[str, Any] | None = None


class TaskArtifactUpdateEvent(BaseModel):
    id: str
    artifact: Artifact
    metadata: dict[str, Any] | None = None


class AuthenticationInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    schemes: list[str]
    credentials: str | None = None


class PushNotificationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    url: str
    token: str | None = None
    authentication: AuthenticationInfo | None = None
    webhook_secret_token: str | None = Field(None, alias="webhookSecretToken")


class TaskIdParams(BaseModel):
    id: str
    metadata: dict[str, Any] | None = None


class TaskQueryParams(TaskIdParams):
    model_config = ConfigDict(populate_by_name=True)
    history_length: int | None = Field(None, alias="historyLength")


class TaskSendParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    context_id: str = Field(default_factory=lambda: uuid4().hex, alias="contextId")
    message: Message
    accepted_output_modes: list[str] | None = Field(None, alias="acceptedOutputModes")
    push_notification: PushNotificationConfig | None = Field(None, alias="pushNotification")
    history_length: int | None = Field(None, alias="historyLength")
    metadata: dict[str, Any] | None = None


class TaskPushNotificationConfig(BaseModel):
    id: str
    push_notification_config: PushNotificationConfig


## RPC Messages


class JSONRPCMessage(BaseModel):
    jsonrpc: Literal["2.0"] = "2.0"
    id: int | str | None = Field(default_factory=lambda: uuid4().hex)


class JSONRPCRequest(JSONRPCMessage):
    method: str
    params: dict[str, Any] | None = None


class JSONRPCError(BaseModel):
    code: int
    message: str
    data: Any | None = None


class JSONRPCResponse(JSONRPCMessage):
    result: Any | None = None
    error: JSONRPCError | None = None


class SendTaskRequest(JSONRPCRequest):
    method: Literal["tasks/send"] = "tasks/send"
    params: TaskSendParams


class SendTaskResponse(JSONRPCResponse):
    result: Task | None = None


class SendTaskStreamingRequest(JSONRPCRequest):
    method: Literal["tasks/sendSubscribe"] = "tasks/sendSubscribe"
    params: TaskSendParams


class SendTaskStreamingResponse(JSONRPCResponse):
    result: TaskStatusUpdateEvent | TaskArtifactUpdateEvent | None = None


class GetTaskRequest(JSONRPCRequest):
    method: Literal["tasks/get"] = "tasks/get"
    params: TaskQueryParams


class GetTaskResponse(JSONRPCResponse):
    result: Task | None = None


class CancelTaskRequest(JSONRPCRequest):
    method: Literal["tasks/cancel",] = "tasks/cancel"
    params: TaskIdParams


class CancelTaskResponse(JSONRPCResponse):
    result: Task | None = None


class SetTaskPushNotificationRequest(JSONRPCRequest):
    method: Literal["tasks/pushNotification/set",] = "tasks/pushNotification/set"
    params: TaskPushNotificationConfig


class SetTaskPushNotificationResponse(JSONRPCResponse):
    result: TaskPushNotificationConfig | None = None


class GetTaskPushNotificationRequest(JSONRPCRequest):
    method: Literal["tasks/pushNotification/get",] = "tasks/pushNotification/get"
    params: TaskIdParams


class GetTaskPushNotificationResponse(JSONRPCResponse):
    result: TaskPushNotificationConfig | None = None


class TaskResubscriptionRequest(JSONRPCRequest):
    method: Literal["tasks/resubscribe",] = "tasks/resubscribe"
    params: TaskIdParams


# A2A Message endpoints
class MessageSendParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    message: Message
    context_id: str | None = Field(None, alias="contextId")
    metadata: dict[str, Any] | None = None


class MessageSendRequest(JSONRPCRequest):
    method: Literal["message/send"] = "message/send"
    params: MessageSendParams


class MessageSendResponse(JSONRPCResponse):
    result: Task | None = None


class MessageStreamRequest(JSONRPCRequest):
    method: Literal["message/stream"] = "message/stream"
    params: MessageSendParams


class MessageStreamResponse(JSONRPCResponse):
    result: TaskStatusUpdateEvent | TaskArtifactUpdateEvent | None = None


# A2A Agent Card types (must be defined before usage)
class AgentProvider(BaseModel):
    organization: str
    url: str | None = None


class AgentCapabilities(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    streaming: bool = False
    push_notifications: bool = Field(False, alias="pushNotifications")
    state_transition_history: bool = Field(False, alias="stateTransitionHistory")


class AgentAuthentication(BaseModel):
    schemes: list[str]
    credentials: str | None = None


class AgentSkill(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str
    name: str
    description: str | None = None
    tags: list[str] | None = None
    examples: list[str] | None = None
    input_modes: list[str] | None = Field(None, alias="inputModes")
    output_modes: list[str] | None = Field(None, alias="outputModes")


class AgentCard(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str
    description: str | None = None
    url: str
    protocol_version: str = Field("0.3.0", alias="protocolVersion")
    version: str = "1.0.0"
    provider: AgentProvider | None = None
    documentation_url: str | None = Field(None, alias="documentationUrl")
    capabilities: AgentCapabilities
    authentication: AgentAuthentication | None = None
    default_input_modes: list[str] = Field(
        default=["text/plain", "application/json"], alias="defaultInputModes"
    )
    default_output_modes: list[str] = Field(
        default=["text/plain", "application/json"], alias="defaultOutputModes"
    )
    skills: list[AgentSkill]
    supports_authenticated_extended_card: bool = Field(
        True, alias="supportsAuthenticatedExtendedCard"
    )
    security_schemes: dict[str, Any] | None = Field(None, alias="securitySchemes")
    security: list[dict[str, list[str]]] | None = None


# A2A Agent Card endpoints
class AuthenticatedExtendedCardParams(BaseModel):
    metadata: dict[str, Any] | None = None


class AuthenticatedExtendedCardRequest(JSONRPCRequest):
    method: Literal["agent/authenticatedExtendedCard"] = "agent/authenticatedExtendedCard"
    params: AuthenticatedExtendedCardParams


class AuthenticatedExtendedCardResponse(JSONRPCResponse):
    result: AgentCard | None = None


# SSE stream response types
class StreamResponseTask(BaseModel):
    """SSE event: initial task object."""

    model_config = ConfigDict(populate_by_name=True)
    kind: Literal["task"] = "task"
    id: str
    context_id: str | None = Field(None, alias="contextId")
    status: TaskStatus
    history: list[Message] | None = None
    artifacts: list[Artifact] | None = None
    metadata: dict[str, Any] | None = None


class StreamResponseStatusUpdate(BaseModel):
    """SSE event: task status change."""

    model_config = ConfigDict(populate_by_name=True)
    kind: Literal["status-update"] = "status-update"
    task_id: str = Field(alias="taskId")
    context_id: str | None = Field(None, alias="contextId")
    status: TaskStatus
    final: bool = False


class StreamResponseArtifactUpdate(BaseModel):
    """SSE event: artifact/output chunk."""

    model_config = ConfigDict(populate_by_name=True)
    kind: Literal["artifact-update"] = "artifact-update"
    task_id: str = Field(alias="taskId")
    context_id: str | None = Field(None, alias="contextId")
    artifact: Artifact
    append: bool = False
    last_chunk: bool = Field(False, alias="lastChunk")


A2ARequest = TypeAdapter(
    Annotated[
        MessageSendRequest
        | MessageStreamRequest
        | SendTaskRequest
        | GetTaskRequest
        | CancelTaskRequest
        | SetTaskPushNotificationRequest
        | GetTaskPushNotificationRequest
        | TaskResubscriptionRequest
        | SendTaskStreamingRequest
        | AuthenticatedExtendedCardRequest,
        Field(discriminator="method"),
    ]
)

## Error types


class JSONParseError(JSONRPCError):
    code: int = -32700
    message: str = "Invalid JSON payload"
    data: Any | None = None


class InvalidRequestError(JSONRPCError):
    code: int = -32600
    message: str = "Request payload validation error"
    data: Any | None = None


class MethodNotFoundError(JSONRPCError):
    code: int = -32601
    message: str = "Method not found"
    data: None = None


class InvalidParamsError(JSONRPCError):
    code: int = -32602
    message: str = "Invalid parameters"
    data: Any | None = None


class InternalError(JSONRPCError):
    code: int = -32603
    message: str = "Internal error"
    data: Any | None = None


class TaskNotFoundError(JSONRPCError):
    code: int = -32001
    message: str = "Task not found"
    data: None = None


class TaskNotCancelableError(JSONRPCError):
    code: int = -32002
    message: str = "Task cannot be canceled"
    data: None = None


class PushNotificationNotSupportedError(JSONRPCError):
    code: int = -32003
    message: str = "Push Notification is not supported"
    data: None = None


class UnsupportedOperationError(JSONRPCError):
    code: int = -32004
    message: str = "This operation is not supported"
    data: None = None


class ContentTypeNotSupportedError(JSONRPCError):
    code: int = -32005
    message: str = "Incompatible content types"
    data: None = None


class VersionNotSupportedError(JSONRPCError):
    code: int = -32007
    message: str = "Version not supported"
    data: None = None


# Duplicate agent card types removed - already defined above


class A2AClientError(Exception):
    pass


class A2AClientHTTPError(A2AClientError):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        self.message = message
        super().__init__(f"HTTP Error {status_code}: {message}")


class A2AClientJSONError(A2AClientError):
    def __init__(self, message: str):
        self.message = message
        super().__init__(f"JSON Error: {message}")


class MissingAPIKeyError(Exception):
    """Exception for missing API key."""


def sanitize_agent_name(name: str) -> str:
    """Sanitize agent name to be a valid Python identifier for Google ADK.

    Google ADK requires agent names to be valid Python identifiers:
    - Must start with a letter (a-z, A-Z) or underscore (_)
    - Can only contain letters, digits (0-9), and underscores

    Args:
        name: The original agent name

    Returns:
        Sanitized agent name that is a valid Python identifier

    Examples:
        >>> sanitize_agent_name("test-agent-123")
        'test_agent_123'
        >>> sanitize_agent_name("123-agent")
        'agent_123'
        >>> sanitize_agent_name("my-cool-agent!")
        'my_cool_agent_'
    """
    if not name:
        return "agent"

    # Replace hyphens and other invalid characters with underscores
    sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", name)

    # Ensure it starts with a letter or underscore
    if sanitized and sanitized[0].isdigit():
        sanitized = f"agent_{sanitized}"

    # Ensure it's not empty
    if not sanitized:
        return "agent"

    # Remove consecutive underscores
    sanitized = re.sub(r"_+", "_", sanitized)

    # Remove trailing underscores (but keep leading ones)
    sanitized = sanitized.rstrip("_")

    # Ensure it's not empty after cleanup
    if not sanitized:
        return "agent"

    return sanitized
