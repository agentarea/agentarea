/**
 * Message accumulation and transformation utilities
 * Pure functions for managing message arrays (LLM chunks, tool calls, etc.)
 */

import { MessageComponentType } from "../MessageComponents";

export interface ChatMessage {
  id: string;
  content: string;
  role: "user" | "assistant";
  timestamp: string;
  files?: File[];
  agent_id?: string;
}

export type AnyMessage = ChatMessage | MessageComponentType;

/**
 * Accumulates an LLM chunk into the messages array
 * If the last message is a streaming chunk from the same task, appends to it
 * Otherwise creates a new streaming message
 */
export function accumulateLLMChunk(
  messages: AnyMessage[],
  chunkData: {
    taskId: string;
    chunk: string;
    chunkIndex: number;
    isFinal: boolean;
    messageComponent: MessageComponentType | null;
  }
): AnyMessage[] {
  const lastMessage = messages[messages.length - 1];

  // Check if the last message is a streaming message from the same task
  if (
    lastMessage &&
    "type" in lastMessage &&
    lastMessage.type === "llm_chunk" &&
    lastMessage.data.id === chunkData.taskId
  ) {
    // Update the existing streaming message
    const updatedMessage: MessageComponentType = {
      ...lastMessage,
      data: {
        ...lastMessage.data,
        chunk: lastMessage.data.chunk + chunkData.chunk,
        chunk_index: chunkData.chunkIndex,
        is_final: chunkData.isFinal,
      },
    };

    return [...messages.slice(0, -1), updatedMessage];
  }

  // Create new streaming message if we have a component
  if (chunkData.messageComponent) {
    return [...messages, chunkData.messageComponent];
  }

  return messages;
}

/**
 * Finalizes an LLM streaming chunk by converting it to a completed message
 */
export function finalizeLLMChunk(
  messages: AnyMessage[],
  taskId: string
): AnyMessage[] {
  const lastMessage = messages[messages.length - 1];

  if (
    lastMessage &&
    "type" in lastMessage &&
    lastMessage.type === "llm_chunk" &&
    lastMessage.data.id === taskId
  ) {
    // Convert to final llm_response message
    const finalMessage: MessageComponentType = {
      type: "llm_response",
      data: {
        id: lastMessage.data.id,
        timestamp: lastMessage.data.timestamp,
        agent_id: lastMessage.data.agent_id,
        event_type: "LLMCallCompleted",
        content: lastMessage.data.chunk,
        role: "assistant",
      },
    };

    return [...messages.slice(0, -1), finalMessage];
  }

  return messages;
}

/**
 * Checks if a tool call has already been started in the messages
 */
export function hasToolCallStarted(
  messages: AnyMessage[],
  toolName: string,
  toolCallId: string
): boolean {
  return messages.some(
    (msg) =>
      "type" in msg &&
      msg.type === "tool_call_started" &&
      (msg.data as any).tool_name === toolName &&
      (msg.data as any).tool_call_id === toolCallId
  );
}

/**
 * Checks if a tool call has already been completed in the messages
 */
export function hasToolCallCompleted(
  messages: AnyMessage[],
  toolName: string,
  toolCallId: string
): boolean {
  return messages.some(
    (msg) =>
      "type" in msg &&
      msg.type === "tool_result" &&
      (msg.data as any).tool_name === toolName &&
      (msg.data as any).tool_call_id === toolCallId
  );
}

/**
 * Replaces a tool_call_started message with a tool_result message
 * Finds the last matching tool_call_started and replaces it
 * If no match found, appends the result message
 */
export function replaceToolCallStarted(
  messages: AnyMessage[],
  toolData: {
    toolName: string;
    toolCallId: string;
    resultMessage: MessageComponentType | null;
  }
): AnyMessage[] {
  if (!toolData.resultMessage) {
    return messages;
  }

  // Find the last tool_call_started message for the same tool and call ID
  const lastToolCallIndex = messages.findLastIndex(
    (msg) =>
      "type" in msg &&
      msg.type === "tool_call_started" &&
      (msg.data as any).tool_name === toolData.toolName &&
      (msg.data as any).tool_call_id === toolData.toolCallId
  );

  if (lastToolCallIndex !== -1) {
    // Replace the tool_call_started message with tool_result
    const newMessages = [...messages];
    newMessages[lastToolCallIndex] = toolData.resultMessage;
    return newMessages;
  }

  // If no matching tool_call_started found, just add the result
  return [...messages, toolData.resultMessage];
}
