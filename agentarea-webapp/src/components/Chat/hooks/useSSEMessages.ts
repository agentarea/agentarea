/**
 * Composite hook for SSE message management
 * Combines SSE connection, message state, and event handling
 */

import { useCallback, useState } from "react";
import { useSSE } from "@/hooks/useSSE";
import { createSSEEventHandler } from "../handlers/eventHandlers";
import { AnyMessage } from "../utils/messageAccumulator";

export interface UseSSEMessagesOptions {
  /**
   * Agent ID
   */
  agentId: string;

  /**
   * Task ID (null if no task yet)
   */
  taskId: string | null;

  /**
   * SSE connection URL (null to skip connection)
   */
  sseUrl: string | null;

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

export interface UseSSEMessagesReturn {
  /**
   * Current messages array
   */
  messages: AnyMessage[];

  /**
   * Set messages array
   */
  setMessages: React.Dispatch<React.SetStateAction<AnyMessage[]>>;

  /**
   * Loading state
   */
  isLoading: boolean;

  /**
   * Set loading state
   */
  setIsLoading: (loading: boolean) => void;

  /**
   * Current task ID
   */
  currentTaskId: string | null;

  /**
   * Set current task ID
   */
  setCurrentTaskId: (id: string | null) => void;
}

/**
 * Custom hook for SSE-based message management
 *
 * This is a composite hook that:
 * - Manages message array state
 * - Manages loading state
 * - Manages current task ID
 * - Connects to SSE stream
 * - Handles all SSE events via createSSEEventHandler
 * - Coordinates lifecycle callbacks
 *
 * @example
 * ```typescript
 * const {
 *   messages,
 *   setMessages,
 *   isLoading,
 *   setIsLoading,
 *   currentTaskId,
 *   setCurrentTaskId
 * } = useSSEMessages({
 *   agentId: 'agent-123',
 *   taskId: null,
 *   sseUrl: null,
 *   onTaskStarted: (id) => router.push(`/tasks/${id}`)
 * });
 * ```
 */
export function useSSEMessages({
  agentId,
  taskId,
  sseUrl,
  onTaskCreated,
  onTaskStarted,
  onTaskFinished,
}: UseSSEMessagesOptions): UseSSEMessagesReturn {
  const [messages, setMessages] = useState<AnyMessage[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [currentTaskId, setCurrentTaskId] = useState<string | null>(
    taskId || null
  );

  // Create SSE event handler with all dependencies
  const handleSSEMessage = useCallback(
    createSSEEventHandler({
      currentTaskId,
      setMessages,
      setIsLoading,
      setCurrentTaskId,
      onTaskCreated,
      onTaskStarted,
      onTaskFinished,
    }),
    [currentTaskId, onTaskCreated, onTaskStarted, onTaskFinished]
  );

  // SSE error handler
  const handleSSEError = useCallback((error: Event) => {
    console.error("SSE connection error:", error);
    setIsLoading(false);
  }, []);

  // SSE open handler
  const handleSSEOpen = useCallback(() => {
    // SSE connection opened
  }, []);

  // SSE close handler
  const handleSSEClose = useCallback(() => {
    // SSE connection closed
  }, []);

  // Initialize SSE connection
  useSSE(sseUrl, {
    onMessage: handleSSEMessage,
    onError: handleSSEError,
    onOpen: handleSSEOpen,
    onClose: handleSSEClose,
  });

  return {
    messages,
    setMessages,
    isLoading,
    setIsLoading,
    currentTaskId,
    setCurrentTaskId,
  };
}
