/**
 * Main SSE event handler factory
 * Creates a centralized handler that delegates to specialized handlers
 */

import { parseEventToMessage, shouldDisplayEvent } from "../EventParser";
import { normalizeEventType } from "../utils/eventNormalizer";
import { AnyMessage } from "../utils/messageAccumulator";
import {
  handleLLMChunk,
  handleToolCallStarted,
  handleToolCallCompleted,
  handleWorkflowCompleted,
  handleTaskCreated,
  handleError,
} from "./messageEventHandlers";
import {
  EVENT_LLM_CALL_CHUNK,
  EVENT_TOOL_CALL_STARTED,
  EVENT_TOOL_CALL_COMPLETED,
  EVENT_WORKFLOW_COMPLETED,
  EVENT_WORKFLOW_FAILED,
  EVENT_TASK_FAILED,
  EVENT_CONNECTED,
  EVENT_TASK_CREATED,
  EVENT_ERROR,
  EVENT_MESSAGE,
} from "../constants/eventTypes";

export interface SSEEventHandlerOptions {
  /**
   * Current task ID (can be null)
   */
  currentTaskId: string | null;

  /**
   * Set the messages array
   */
  setMessages: React.Dispatch<React.SetStateAction<AnyMessage[]>>;

  /**
   * Set loading state
   */
  setIsLoading: (loading: boolean) => void;

  /**
   * Set current task ID
   */
  setCurrentTaskId: (id: string | null) => void;

  /**
   * Callback when task is created
   */
  onTaskCreated?: (taskId: string) => void;

  /**
   * Callback when task is started
   */
  onTaskStarted?: (taskId: string) => void;

  /**
   * Callback when task is finished
   */
  onTaskFinished?: (taskId: string) => void;
}

/**
 * Creates an SSE event handler function
 *
 * This is the main event processing pipeline that:
 * 1. Normalizes event types
 * 2. Filters out non-displayable events
 * 3. Delegates to specialized handlers
 * 4. Handles system events (task_created, error, etc.)
 * 5. Parses and adds regular message events
 *
 * @param options - Handler configuration
 * @returns Event handler function
 *
 * @example
 * ```typescript
 * const handleSSEMessage = createSSEEventHandler({
 *   currentTaskId: null,
 *   setMessages,
 *   setIsLoading,
 *   setCurrentTaskId,
 *   onTaskStarted: (id) => router.push(`/tasks/${id}`)
 * });
 *
 * // Use with SSE connection
 * useSSE(sseUrl, { onMessage: handleSSEMessage });
 * ```
 */
export function createSSEEventHandler(
  options: SSEEventHandlerOptions
): (event: { type: string; data: any }) => void {
  const {
    currentTaskId,
    setMessages,
    setIsLoading,
    setCurrentTaskId,
    onTaskCreated,
    onTaskStarted,
    onTaskFinished,
  } = options;

  return (event: { type: string; data: any }) => {
    // Get the actual event type from the data if available
    const actualEventType =
      event.data?.event_type || event.data?.original_event_type || event.type;

    // Handle generic "message" events that might be heartbeats or connection events
    if (actualEventType === EVENT_MESSAGE && !event.data?.event_type) {
      // This is likely a heartbeat or connection event - just return
      return;
    }

    // Normalize to canonical event type
    const cleanEventType = normalizeEventType(actualEventType);

    // Check if this event should create a visible message
    if (!shouldDisplayEvent(cleanEventType)) {
      return;
    }

    // Special handling for LLM chunk events - accumulate instead of creating new messages
    if (cleanEventType === EVENT_LLM_CALL_CHUNK) {
      handleLLMChunk(event, setMessages);
      return;
    }

    // Special handling for tool call events
    if (cleanEventType === EVENT_TOOL_CALL_STARTED) {
      handleToolCallStarted(event, setMessages);
      return;
    }

    if (cleanEventType === EVENT_TOOL_CALL_COMPLETED) {
      handleToolCallCompleted(event, setMessages);
      return;
    }

    // Clear any loading state FIRST - before message parsing
    if (
      cleanEventType === EVENT_WORKFLOW_COMPLETED ||
      cleanEventType === EVENT_WORKFLOW_FAILED ||
      cleanEventType === EVENT_TASK_FAILED
    ) {
      handleWorkflowCompleted(event, {
        setIsLoading,
        onTaskFinished,
        currentTaskId,
      });
    }

    // Handle special system events FIRST, before checking if they create visible messages
    switch (cleanEventType) {
      case EVENT_CONNECTED:
        break;

      case EVENT_TASK_CREATED:
        handleTaskCreated(event, {
          currentTaskId,
          setCurrentTaskId,
          onTaskCreated,
          onTaskStarted,
        });
        break;

      case EVENT_ERROR:
        handleError(setIsLoading);
        break;

      default:
        break;
    }

    // Parse event into message component for display
    const messageComponent = parseEventToMessage(cleanEventType, event.data);
    if (!messageComponent) {
      return;
    }

    // Add the new message component to the messages
    setMessages((prev) => [...prev, messageComponent]);
  };
}
