/**
 * Canonical event type constants
 * Use these constants throughout the codebase instead of hardcoded strings
 */

// Workflow events
export const EVENT_WORKFLOW_STARTED = "WorkflowStarted";
export const EVENT_WORKFLOW_COMPLETED = "WorkflowCompleted";
export const EVENT_WORKFLOW_FAILED = "WorkflowFailed";
export const EVENT_WORKFLOW_CANCELLED = "WorkflowCancelled";

// LLM events
export const EVENT_LLM_CALL_STARTED = "LLMCallStarted";
export const EVENT_LLM_CALL_COMPLETED = "LLMCallCompleted";
export const EVENT_LLM_CALL_FAILED = "LLMCallFailed";
export const EVENT_LLM_CALL_CHUNK = "LLMCallChunk";

// Tool events
export const EVENT_TOOL_CALL_STARTED = "ToolCallStarted";
export const EVENT_TOOL_CALL_COMPLETED = "ToolCallCompleted";
export const EVENT_TOOL_CALL_FAILED = "ToolCallFailed";

// Approval events
export const EVENT_HUMAN_APPROVAL_REQUESTED = "HumanApprovalRequested";
export const EVENT_HUMAN_APPROVAL_RECEIVED = "HumanApprovalReceived";
export const EVENT_HUMAN_APPROVAL_DENIED = "HumanApprovalDenied";

// Structured user-input request events (request_user_input tool; supports secret fields)
export const EVENT_HUMAN_INPUT_REQUESTED = "HumanInputRequested";
export const EVENT_HUMAN_INPUT_RECEIVED = "HumanInputReceived";

// Context events
export const EVENT_CONTEXT_WARNING = "ContextWarning";
export const EVENT_CONTEXT_COMPACTED = "ContextCompacted";

// A2UI events (v0.9 protocol)
export const EVENT_A2UI_CREATE_SURFACE = "A2UICreateSurface";
export const EVENT_A2UI_UPDATE_COMPONENTS = "A2UIUpdateComponents";
export const EVENT_A2UI_UPDATE_DATA_MODEL = "A2UIUpdateDataModel";
export const EVENT_A2UI_DELETE_SURFACE = "A2UIDeleteSurface";

// System events
export const EVENT_CONNECTED = "connected";
export const EVENT_TASK_CREATED = "task_created";
export const EVENT_TASK_FAILED = "task_failed";
export const EVENT_ERROR = "error";
export const EVENT_MESSAGE = "message";

/**
 * All canonical event types
 */
export const CANONICAL_EVENT_TYPES = {
  // Workflow
  WORKFLOW_STARTED: EVENT_WORKFLOW_STARTED,
  WORKFLOW_COMPLETED: EVENT_WORKFLOW_COMPLETED,
  WORKFLOW_FAILED: EVENT_WORKFLOW_FAILED,
  WORKFLOW_CANCELLED: EVENT_WORKFLOW_CANCELLED,

  // LLM
  LLM_CALL_STARTED: EVENT_LLM_CALL_STARTED,
  LLM_CALL_COMPLETED: EVENT_LLM_CALL_COMPLETED,
  LLM_CALL_FAILED: EVENT_LLM_CALL_FAILED,
  LLM_CALL_CHUNK: EVENT_LLM_CALL_CHUNK,

  // Tool
  TOOL_CALL_STARTED: EVENT_TOOL_CALL_STARTED,
  TOOL_CALL_COMPLETED: EVENT_TOOL_CALL_COMPLETED,
  TOOL_CALL_FAILED: EVENT_TOOL_CALL_FAILED,

  // Approval
  HUMAN_APPROVAL_REQUESTED: EVENT_HUMAN_APPROVAL_REQUESTED,
  HUMAN_APPROVAL_RECEIVED: EVENT_HUMAN_APPROVAL_RECEIVED,
  HUMAN_APPROVAL_DENIED: EVENT_HUMAN_APPROVAL_DENIED,

  // Context
  CONTEXT_WARNING: EVENT_CONTEXT_WARNING,
  CONTEXT_COMPACTED: EVENT_CONTEXT_COMPACTED,

  // A2UI
  A2UI_CREATE_SURFACE: EVENT_A2UI_CREATE_SURFACE,
  A2UI_UPDATE_COMPONENTS: EVENT_A2UI_UPDATE_COMPONENTS,
  A2UI_UPDATE_DATA_MODEL: EVENT_A2UI_UPDATE_DATA_MODEL,
  A2UI_DELETE_SURFACE: EVENT_A2UI_DELETE_SURFACE,

  // System
  CONNECTED: EVENT_CONNECTED,
  TASK_CREATED: EVENT_TASK_CREATED,
  TASK_FAILED: EVENT_TASK_FAILED,
  ERROR: EVENT_ERROR,
  MESSAGE: EVENT_MESSAGE,
} as const;

/**
 * Type for canonical event names
 */
export type CanonicalEventType = typeof CANONICAL_EVENT_TYPES[keyof typeof CANONICAL_EVENT_TYPES];
