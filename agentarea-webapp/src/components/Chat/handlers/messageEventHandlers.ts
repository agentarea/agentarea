/**
 * Type-specific message event handlers
 * Handles LLM chunks, tool calls, and workflow events
 */

import { parseEventToMessage } from "../EventParser";
import { MessageComponentType } from "../MessageComponents";
import {
  accumulateLLMChunk,
  finalizeLLMChunk,
  hasToolCallStarted,
  hasToolCallCompleted,
  replaceToolCallStarted,
  AnyMessage,
} from "../utils/messageAccumulator";
import {
  EVENT_LLM_CALL_CHUNK,
  EVENT_TOOL_CALL_STARTED,
  EVENT_TOOL_CALL_COMPLETED,
} from "../constants/eventTypes";

/**
 * Handle LLM chunk events (streaming text)
 * Accumulates chunks into existing streaming message or creates new one
 */
export function handleLLMChunk(
  event: any,
  setMessages: React.Dispatch<React.SetStateAction<AnyMessage[]>>
): void {
  const originalData = event.data.original_data || event.data;
  const chunk = originalData.chunk || event.data.chunk;
  const chunkIndex = originalData.chunk_index || event.data.chunk_index || 0;
  const isFinal = originalData.is_final || event.data.is_final || false;
  const taskId = originalData.task_id || event.data.task_id;

  // Accumulate chunk
  setMessages((prev) => {
    const messageComponent = parseEventToMessage(EVENT_LLM_CALL_CHUNK, event.data);
    return accumulateLLMChunk(prev, {
      taskId,
      chunk,
      chunkIndex,
      isFinal,
      messageComponent,
    });
  });

  // Finalize if this is the last chunk
  if (isFinal) {
    setMessages((prev) => finalizeLLMChunk(prev, taskId));
  }
}

/**
 * Handle tool call started events
 * Adds a placeholder message for the tool call
 */
export function handleToolCallStarted(
  event: any,
  setMessages: React.Dispatch<React.SetStateAction<AnyMessage[]>>
): void {
  const originalData = event.data.original_data || event.data;
  const toolName = originalData.tool_name || event.data.tool_name;
  const toolCallId = originalData.tool_call_id || event.data.tool_call_id;

  setMessages((prev) => {
    // Check if this tool call has already been started (deduplication)
    if (hasToolCallStarted(prev, toolName, toolCallId)) {
      return prev;
    }

    // Create new tool call started message
    const messageComponent = parseEventToMessage(EVENT_TOOL_CALL_STARTED, event.data);
    if (messageComponent) {
      return [...prev, messageComponent];
    }
    return prev;
  });
}

/**
 * Handle tool call completed events
 * Replaces the tool_call_started message with the result
 */
export function handleToolCallCompleted(
  event: any,
  setMessages: React.Dispatch<React.SetStateAction<AnyMessage[]>>
): void {
  const originalData = event.data.original_data || event.data;
  const toolName = originalData.tool_name || event.data.tool_name;
  const toolCallId = originalData.tool_call_id || event.data.tool_call_id;

  setMessages((prev) => {
    // Check if this tool call has already been completed (deduplication)
    if (hasToolCallCompleted(prev, toolName, toolCallId)) {
      return prev;
    }

    // Replace tool_call_started with tool_result
    const messageComponent = parseEventToMessage(
      EVENT_TOOL_CALL_COMPLETED,
      event.data
    );
    return replaceToolCallStarted(prev, {
      toolName,
      toolCallId,
      resultMessage: messageComponent,
    });
  });
}

/**
 * Handle workflow completion events (success or failure)
 * Clears loading state and triggers onTaskFinished callback
 */
export function handleWorkflowCompleted(
  event: any,
  options: {
    setIsLoading: (loading: boolean) => void;
    onTaskFinished?: (taskId: string) => void;
    currentTaskId: string | null;
  }
): void {
  const { setIsLoading, onTaskFinished, currentTaskId } = options;

  setIsLoading(false);

  // Call onTaskFinished callback if available
  const taskId = currentTaskId || event.data?.task_id;
  if (onTaskFinished && taskId) {
    onTaskFinished(taskId);
  }
}

/**
 * Handle task creation events
 * Sets the current task ID and triggers lifecycle callbacks
 */
export function handleTaskCreated(
  event: any,
  options: {
    currentTaskId: string | null;
    setCurrentTaskId: (id: string | null) => void;
    onTaskCreated?: (taskId: string) => void;
    onTaskStarted?: (taskId: string) => void;
  }
): void {
  const { currentTaskId, setCurrentTaskId, onTaskCreated, onTaskStarted } =
    options;

  if (event.data.task_id && !currentTaskId) {
    setCurrentTaskId(event.data.task_id);
    onTaskCreated?.(event.data.task_id);
    onTaskStarted?.(event.data.task_id);
  }
}

/**
 * Handle error events
 * Clears loading state
 */
export function handleError(setIsLoading: (loading: boolean) => void): void {
  setIsLoading(false);
}
