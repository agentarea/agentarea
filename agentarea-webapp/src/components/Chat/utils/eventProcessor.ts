/**
 * Shared event processing logic for converting raw events into chat messages.
 * Used by both the task details page (historical events) and workplace (live SSE).
 * This ensures consistent behavior across all pages that display task execution.
 */

import { parseEventToMessage, shouldDisplayEvent } from "../EventParser";
import { LLMChunkData, MessageComponentType, ToolCallGroupData, ToolResultData, ToolCallStartedData } from "../types";
import { normalizeEventType } from "./eventNormalizer";

interface RawEvent {
  type: string;
  timestamp: Date | string;
  data?: Record<string, any>;
}

interface ProcessEventsOptions {
  taskId: string;
  agentId: string;
}

/**
 * Process an array of historical events into renderable chat messages.
 *
 * Handles:
 * - Event normalization and display filtering
 * - LLM chunk accumulation (merges sequential chunks into single messages)
 * - Thinking block accumulation (separates thinking from text chunks)
 * - Tool call deduplication (replaces started with completed)
 */
export function processEventsToMessages(
  events: RawEvent[],
  options: ProcessEventsOptions
): MessageComponentType[] {
  const messages: MessageComponentType[] = [];
  let pendingChunk: { type: "llm_chunk"; data: LLMChunkData } | null = null;

  for (const event of events) {
    const eventType = normalizeEventType(event.type);
    if (!shouldDisplayEvent(eventType)) continue;

    const eventData: Record<string, any> = {
      ...(event.data || {}),
      task_id: options.taskId,
      agent_id: options.agentId,
      timestamp:
        event.timestamp instanceof Date
          ? event.timestamp.toISOString()
          : event.timestamp,
    };

    // Accumulate LLM chunks into a single message
    if (eventType === "LLMCallChunk") {
      const originalData = eventData.original_data || eventData;
      const chunk: string = originalData.chunk || eventData.chunk || "";
      const chunkType: string =
        originalData.chunk_type || eventData.chunk_type || "text";
      const isFinal: boolean =
        originalData.is_final || eventData.is_final || false;

      if (!pendingChunk) {
        // Start new chunk accumulation
        const message = parseEventToMessage(eventType, eventData);
        if (message && message.type === "llm_chunk") {
          const base = message.data as LLMChunkData;
          pendingChunk =
            chunkType === "thinking"
              ? {
                  type: "llm_chunk",
                  data: { ...base, thinking: chunk, chunk: "", chunk_type: "thinking" },
                }
              : {
                  type: "llm_chunk",
                  data: { ...base, chunk_type: "text" },
                };
        }
      } else {
        // Accumulate into existing chunk
        const prev: LLMChunkData = pendingChunk.data;
        if (chunkType === "thinking") {
          pendingChunk = {
            type: "llm_chunk",
            data: {
              ...prev,
              thinking: (prev.thinking || "") + chunk,
            },
          };
        } else {
          pendingChunk = {
            type: "llm_chunk",
            data: {
              ...prev,
              chunk: prev.chunk + chunk,
            },
          };
        }
      }

      // Finalize on is_final
      if (isFinal && pendingChunk) {
        const d = pendingChunk.data;
        messages.push({
          type: "llm_response",
          data: {
            id: d.id,
            timestamp: d.timestamp,
            agent_id: d.agent_id,
            event_type: "LLMCallCompleted",
            content: d.chunk,
            thinking: d.thinking || undefined,
            role: "assistant",
          },
        });
        pendingChunk = null;
      }
      continue;
    }

    // Tool call deduplication: ToolCallCompleted/Failed replaces the matching
    // ToolCallStarted so the UI swaps pending → result/error in place.
    if (eventType === "ToolCallCompleted" || eventType === "ToolCallFailed") {
      const toolCallId =
        eventData.original_data?.tool_call_id || eventData.tool_call_id;
      const startedIndex = messages.findLastIndex(
        (msg) =>
          msg.type === "tool_call_started" &&
          (msg.data as any).tool_call_id === toolCallId
      );
      const message = parseEventToMessage(eventType, eventData);
      if (message) {
        if (startedIndex !== -1) {
          messages[startedIndex] = message;
        } else {
          messages.push(message);
        }
      }
      continue;
    }

    // Deduplicate consecutive errors (e.g. Temporal workflow retries)
    if (eventType === "WorkflowFailed" || eventType === "task_failed") {
      const message = parseEventToMessage(eventType, eventData);
      if (message && message.type === "error") {
        const lastMsg = messages[messages.length - 1];
        if (
          lastMsg?.type === "error" &&
          (lastMsg.data as any).error === (message.data as any).error
        ) {
          // Same error repeated — skip duplicate
          continue;
        }
      }
      if (message) messages.push(message);
      continue;
    }

    // Skip WorkflowStarted for retried workflows (preceding a duplicate failure)
    if (eventType === "WorkflowStarted") {
      const message = parseEventToMessage(eventType, eventData);
      if (message) messages.push(message);
      continue;
    }

    // Default: parse and add
    const message = parseEventToMessage(eventType, eventData);
    if (message) {
      messages.push(message);
    }
  }

  // If there's a pending (non-finalized) chunk, push it as-is
  if (pendingChunk) {
    messages.push(pendingChunk);
  }

  return groupToolMessages(messages);
}

/**
 * Merge consecutive tool_result and tool_call_started messages into tool_call_group messages.
 * The "completion" tool is excluded from grouping (it's the final answer).
 * A group ends when the next message is not a tool_result or tool_call_started.
 */
function groupToolMessages(messages: MessageComponentType[]): MessageComponentType[] {
  const result: MessageComponentType[] = [];

  for (let i = 0; i < messages.length; i++) {
    const msg = messages[i];

    if (msg.type !== "tool_result" && msg.type !== "tool_call_started") {
      result.push(msg);
      continue;
    }

    // Check if this is the "completion" tool — never group it
    const toolName = (msg.data as ToolResultData | ToolCallStartedData).tool_name;
    if (toolName === "completion") {
      result.push(msg);
      continue;
    }

    // Start a new group, collecting all consecutive tool messages
    const groupTools: ToolCallGroupData["tools"] = [];
    const groupId = msg.data.id;
    const groupTimestamp = msg.data.timestamp;
    const agentId = msg.data.agent_id;

    let j = i;
    while (j < messages.length) {
      const cur = messages[j];
      if (cur.type !== "tool_result" && cur.type !== "tool_call_started") break;

      const curToolName = (cur.data as ToolResultData | ToolCallStartedData).tool_name;
      if (curToolName === "completion") break;

      if (cur.type === "tool_result") {
        const d = cur.data as ToolResultData;
        groupTools.push({
          tool_name: d.tool_name,
          tool_call_id: d.tool_call_id,
          result: d.result,
          success: d.success,
          arguments: d.arguments,
          execution_time: d.execution_time,
          pending: false,
          server_name: d.server_name,
          server_icon: d.server_icon,
        });
      } else {
        // tool_call_started
        const d = cur.data as ToolCallStartedData;
        groupTools.push({
          tool_name: d.tool_name,
          tool_call_id: d.tool_call_id,
          result: null,
          success: true,
          arguments: d.arguments,
          pending: true,
          server_name: d.server_name,
          server_icon: d.server_icon,
        });
      }
      j++;
    }

    // Only create a group if there are 2+ tools; otherwise keep single message as-is
    if (groupTools.length >= 2) {
      result.push({
        type: "tool_call_group",
        data: {
          id: groupId,
          timestamp: groupTimestamp,
          agent_id: agentId,
          event_type: "tool_call_group",
          tools: groupTools,
        },
      });
      i = j - 1; // skip consumed messages (loop will i++)
    } else {
      result.push(msg);
    }
  }

  return result;
}
