/**
 * Shared event processing logic for converting raw events into chat messages.
 * Used by both the task details page (historical events) and workplace (live SSE).
 * This ensures consistent behavior across all pages that display task execution.
 */

import { parseEventToMessage, shouldDisplayEvent } from "../EventParser";
import { LLMChunkData, MessageComponentType } from "../types";
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

    // Tool call deduplication: if we see ToolCallCompleted, replace matching ToolCallStarted
    if (eventType === "ToolCallCompleted") {
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

  return messages;
}
