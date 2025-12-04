/**
 * Event type normalization utilities for SSE events
 * Maps various event type formats to canonical UI-friendly names
 */

import {
  EVENT_WORKFLOW_STARTED,
  EVENT_WORKFLOW_COMPLETED,
  EVENT_WORKFLOW_FAILED,
  EVENT_WORKFLOW_CANCELLED,
  EVENT_LLM_CALL_STARTED,
  EVENT_LLM_CALL_COMPLETED,
  EVENT_LLM_CALL_FAILED,
  EVENT_LLM_CALL_CHUNK,
  EVENT_TOOL_CALL_STARTED,
  EVENT_TOOL_CALL_COMPLETED,
  EVENT_TOOL_CALL_FAILED,
} from "../constants/eventTypes";

export const EVENT_TYPE_MAP: Record<string, string> = {
  // workflow core
  workflowstarted: EVENT_WORKFLOW_STARTED,
  workflowcompleted: EVENT_WORKFLOW_COMPLETED,
  workflowfailed: EVENT_WORKFLOW_FAILED,
  workflowcancelled: EVENT_WORKFLOW_CANCELLED,
  started: EVENT_WORKFLOW_STARTED,
  completed: EVENT_WORKFLOW_COMPLETED,
  failed: EVENT_WORKFLOW_FAILED,
  cancelled: EVENT_WORKFLOW_CANCELLED,
  // llm
  llmcallstarted: EVENT_LLM_CALL_STARTED,
  llmcallcompleted: EVENT_LLM_CALL_COMPLETED,
  llmcallfailed: EVENT_LLM_CALL_FAILED,
  llmcallchunk: EVENT_LLM_CALL_CHUNK,
  // tool
  toolcallstarted: EVENT_TOOL_CALL_STARTED,
  toolcallcompleted: EVENT_TOOL_CALL_COMPLETED,
  toolcallfailed: EVENT_TOOL_CALL_FAILED,
  // task-level aliases
  taskcompleted: EVENT_WORKFLOW_COMPLETED,
  taskfailed: EVENT_WORKFLOW_FAILED,
  taskcancelled: EVENT_WORKFLOW_CANCELLED,
};

/**
 * Normalizes event types to UI-friendly canonical names
 *
 * @param type - Raw event type from SSE stream
 * @returns Canonical event type name
 *
 * @example
 * normalizeEventType("llm_call_completed") // "LLMCallCompleted"
 * normalizeEventType("workflow.started") // "WorkflowStarted"
 * normalizeEventType("task_completed") // "WorkflowCompleted"
 */
export function normalizeEventType(type: string): string {
  const key = (type || "").toLowerCase().replace(/[^a-z]/g, "");
  return EVENT_TYPE_MAP[key] || type.replace("workflow.", "");
}
