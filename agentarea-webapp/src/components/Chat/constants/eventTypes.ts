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
