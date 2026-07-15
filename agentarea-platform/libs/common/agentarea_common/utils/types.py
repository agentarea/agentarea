import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    PlainSerializer,
    TypeAdapter,
    field_serializer,
    model_serializer,
)


def _utc_z_isoformat(dt: datetime) -> str:
    """Render a datetime as RFC 3339 UTC with a trailing ``Z``.

    DB timestamps are naive UTC (``TIMESTAMP WITHOUT TIME ZONE``); serialized
    plainly they come out without an offset (``...042386``), which strict clients
    reject — notably Zod's ``z.string().datetime()``, which requires a ``Z``. We
    treat naive values as UTC and emit ``...042386Z``.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


# Reusable field type for API response datetimes: JSON-serializes as UTC ``Z``.
UtcDatetime = Annotated[
    datetime, PlainSerializer(_utc_z_isoformat, return_type=str, when_used="json")
]


class TaskState(StrEnum):
    # A2A v1.0.0 wire values use proto SCREAMING_SNAKE encoding.
    SUBMITTED = "SUBMITTED"
    WORKING = "WORKING"
    INPUT_REQUIRED = "INPUT_REQUIRED"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    COMPLETED = "COMPLETED"
    CANCELED = "CANCELED"
    FAILED = "FAILED"
    REJECTED = "REJECTED"
    UNKNOWN = "TASK_STATE_UNSPECIFIED"


class Part(BaseModel):
    """A2A v1.0.0 flat Part — a single model spanning text/file/data content.

    Serializes ONLY the set (non-None) fields, always camelCase (``mediaType``),
    and never emits a ``kind`` discriminator. A bare text part serializes to
    exactly ``{"text": "..."}``.
    """

    model_config = ConfigDict(populate_by_name=True)
    text: str | None = None
    data: dict[str, Any] | None = None
    raw: str | None = None  # base64-encoded bytes
    url: str | None = None
    filename: str | None = None
    media_type: str | None = Field(default=None, alias="mediaType")
    metadata: dict[str, Any] | None = None

    @model_serializer
    def _serialize(self) -> dict[str, Any]:
        out: dict[str, Any] = {}
        if self.text is not None:
            out["text"] = self.text
        if self.data is not None:
            out["data"] = self.data
        if self.raw is not None:
            out["raw"] = self.raw
        if self.url is not None:
            out["url"] = self.url
        if self.filename is not None:
            out["filename"] = self.filename
        if self.media_type is not None:
            out["mediaType"] = self.media_type
        if self.metadata is not None:
            out["metadata"] = self.metadata
        return out


def TextPart(text: str, metadata: dict[str, Any] | None = None) -> Part:  # noqa: N802
    """Convenience constructor for a text-only :class:`Part` (PascalCase by design)."""
    return Part(text=text, metadata=metadata)


class Message(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    role: Literal["USER", "AGENT"]
    parts: list[Part]
    message_id: str = Field(default_factory=lambda: uuid4().hex, alias="messageId")
    task_id: str | None = Field(default=None, alias="taskId")
    context_id: str | None = Field(default=None, alias="contextId")
    reference_task_ids: list[str] | None = Field(default=None, alias="referenceTaskIds")
    extensions: list[str] | None = None
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
    last_chunk: bool | None = Field(default=None, alias="lastChunk")


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
    metadata: dict[str, Any] | None = None


class TaskArtifactUpdateEvent(BaseModel):
    id: str
    artifact: Artifact
    metadata: dict[str, Any] | None = None


class AuthenticationInfo(BaseModel):
    model_config = ConfigDict(extra="allow")

    scheme: str
    credentials: str | None = None


class PushNotificationConfig(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    id: str | None = None
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
    """A2A v1.0.0 flat push-notification config (no nested object)."""

    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(alias="taskId")
    id: str | None = None
    url: str
    token: str | None = None
    authentication: AuthenticationInfo | None = None
    tenant: str | None = None


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


class GetTaskRequest(JSONRPCRequest):
    method: Literal["GetTask"] = "GetTask"
    params: TaskQueryParams | None = None


class GetTaskResponse(JSONRPCResponse):
    result: Task | None = None


class CancelTaskRequest(JSONRPCRequest):
    method: Literal["CancelTask"] = "CancelTask"
    params: TaskIdParams | None = None


class CancelTaskResponse(JSONRPCResponse):
    result: Task | None = None


class ListTasksRequest(JSONRPCRequest):
    method: Literal["ListTasks"] = "ListTasks"
    params: dict[str, Any] | None = None


class CreateTaskPushNotificationConfigRequest(JSONRPCRequest):
    method: Literal["CreateTaskPushNotificationConfig"] = "CreateTaskPushNotificationConfig"
    params: TaskPushNotificationConfig | None = None


class CreateTaskPushNotificationConfigResponse(JSONRPCResponse):
    result: TaskPushNotificationConfig | None = None


class GetTaskPushNotificationConfigRequest(JSONRPCRequest):
    method: Literal["GetTaskPushNotificationConfig"] = "GetTaskPushNotificationConfig"
    params: TaskIdParams | None = None


class GetTaskPushNotificationConfigResponse(JSONRPCResponse):
    result: TaskPushNotificationConfig | None = None


class ListTaskPushNotificationConfigsRequest(JSONRPCRequest):
    method: Literal["ListTaskPushNotificationConfigs"] = "ListTaskPushNotificationConfigs"
    params: TaskIdParams | None = None


class DeleteTaskPushNotificationConfigRequest(JSONRPCRequest):
    method: Literal["DeleteTaskPushNotificationConfig"] = "DeleteTaskPushNotificationConfig"
    params: TaskIdParams | None = None


class SubscribeToTaskRequest(JSONRPCRequest):
    method: Literal["SubscribeToTask"] = "SubscribeToTask"
    params: TaskIdParams | None = None


# A2A Message endpoints
class SendMessageConfiguration(BaseModel):
    """A2A v1.0.0 SendMessageConfiguration — per-send options incl. push registration."""

    model_config = ConfigDict(populate_by_name=True)
    accepted_output_modes: list[str] | None = Field(None, alias="acceptedOutputModes")
    history_length: int | None = Field(None, alias="historyLength")
    task_push_notification_config: TaskPushNotificationConfig | None = Field(
        None, alias="taskPushNotificationConfig"
    )
    blocking: bool | None = None


class MessageSendParams(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    message: Message
    context_id: str | None = Field(None, alias="contextId")
    configuration: SendMessageConfiguration | None = None
    metadata: dict[str, Any] | None = None


class MessageSendRequest(JSONRPCRequest):
    method: Literal["SendMessage"] = "SendMessage"
    params: MessageSendParams | None = None


class MessageSendResponse(JSONRPCResponse):
    result: Task | None = None


class MessageStreamRequest(JSONRPCRequest):
    method: Literal["SendStreamingMessage"] = "SendStreamingMessage"
    params: MessageSendParams | None = None


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
    extended_agent_card: bool = Field(False, alias="extendedAgentCard")
    extensions: list[dict[str, Any]] | None = None


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
    security_requirements: list[dict[str, list[str]]] | None = Field(
        default=None, alias="securityRequirements"
    )


class AgentInterface(BaseModel):
    """A2A v1.0.0 AgentInterface — a (url, protocolBinding, protocolVersion) tuple."""

    model_config = ConfigDict(populate_by_name=True)
    url: str
    protocol_binding: str = Field("JSONRPC", alias="protocolBinding")
    protocol_version: str = Field("1.0", alias="protocolVersion")
    tenant: str | None = None


class AgentCard(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    name: str
    description: str | None = None
    # The ONLY interface list; first entry is the preferred interface.
    supported_interfaces: list[AgentInterface] = Field(alias="supportedInterfaces")
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
    security_schemes: dict[str, Any] | None = Field(None, alias="securitySchemes")
    security: list[dict[str, list[str]]] | None = None


# A2A Agent Card endpoints
class ExtendedAgentCardParams(BaseModel):
    metadata: dict[str, Any] | None = None


class GetExtendedAgentCardRequest(JSONRPCRequest):
    method: Literal["GetExtendedAgentCard"] = "GetExtendedAgentCard"
    params: ExtendedAgentCardParams | None = None


class GetExtendedAgentCardResponse(JSONRPCResponse):
    result: AgentCard | None = None


# SSE StreamResponse oneof members (no ``kind`` discriminators; wrapped by member name)
class StreamResponseTask(BaseModel):
    """StreamResponse member: initial task object."""

    model_config = ConfigDict(populate_by_name=True)
    id: str
    context_id: str | None = Field(None, alias="contextId")
    status: TaskStatus
    history: list[Message] | None = None
    artifacts: list[Artifact] | None = None
    metadata: dict[str, Any] | None = None


class StreamResponseStatusUpdate(BaseModel):
    """StreamResponse member: task status change."""

    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(alias="taskId")
    context_id: str | None = Field(None, alias="contextId")
    status: TaskStatus
    metadata: dict[str, Any] | None = None


class StreamResponseArtifactUpdate(BaseModel):
    """StreamResponse member: artifact/output chunk."""

    model_config = ConfigDict(populate_by_name=True)
    task_id: str = Field(alias="taskId")
    context_id: str | None = Field(None, alias="contextId")
    artifact: Artifact
    append: bool = False
    last_chunk: bool = Field(False, alias="lastChunk")
    metadata: dict[str, Any] | None = None


A2ARequest = TypeAdapter(
    Annotated[
        MessageSendRequest
        | MessageStreamRequest
        | GetTaskRequest
        | CancelTaskRequest
        | ListTasksRequest
        | CreateTaskPushNotificationConfigRequest
        | GetTaskPushNotificationConfigRequest
        | ListTaskPushNotificationConfigsRequest
        | DeleteTaskPushNotificationConfigRequest
        | SubscribeToTaskRequest
        | GetExtendedAgentCardRequest,
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


class InvalidAgentResponseError(JSONRPCError):
    code: int = -32006
    message: str = "Invalid agent response"
    data: None = None


class ExtendedAgentCardNotConfiguredError(JSONRPCError):
    code: int = -32007
    message: str = "Extended Agent Card is not configured"
    data: None = None


class ExtensionSupportRequiredError(JSONRPCError):
    code: int = -32008
    message: str = "Extension support is required"
    data: None = None


class VersionNotSupportedError(JSONRPCError):
    code: int = -32009
    message: str = "A2A version not supported"
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
