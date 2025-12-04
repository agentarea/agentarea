/**
 * Hook for managing task lifecycle
 * Handles task ID state, SSE URL construction, and lifecycle callbacks
 */

import { useEffect, useRef, useState } from "react";

export interface UseTaskLifecycleOptions {
  /**
   * Initial task ID (if resuming an existing task)
   */
  initialTaskId?: string;

  /**
   * Callback when task is created
   */
  onTaskCreated?: (taskId: string) => void;

  /**
   * Callback when task is started
   */
  onTaskStarted?: (taskId: string) => void;

  /**
   * Callback when task is finished (completed or failed)
   */
  onTaskFinished?: (taskId: string) => void;
}

export interface UseTaskLifecycleReturn {
  /**
   * Current task ID (null if no task)
   */
  currentTaskId: string | null;

  /**
   * Set the current task ID
   */
  setCurrentTaskId: (id: string | null) => void;

  /**
   * SSE connection URL (null if no task)
   */
  sseUrl: string | null;

  /**
   * Refs for callbacks (stable references)
   */
  callbacks: {
    onTaskCreated: React.MutableRefObject<
      ((taskId: string) => void) | undefined
    >;
    onTaskStarted: React.MutableRefObject<
      ((taskId: string) => void) | undefined
    >;
    onTaskFinished: React.MutableRefObject<
      ((taskId: string) => void) | undefined
    >;
  };
}

/**
 * Custom hook for managing task lifecycle
 *
 * Features:
 * - Task ID state management
 * - SSE URL construction
 * - Stable callback refs
 * - Lifecycle event handling
 *
 * @example
 * ```typescript
 * const {
 *   currentTaskId,
 *   setCurrentTaskId,
 *   sseUrl,
 *   callbacks
 * } = useTaskLifecycle('agent-123', {
 *   onTaskCreated: (id) => console.log('Created:', id),
 *   onTaskStarted: (id) => router.push(`/tasks/${id}`),
 *   onTaskFinished: (id) => console.log('Finished:', id)
 * });
 * ```
 */
export function useTaskLifecycle(
  agentId: string,
  options: UseTaskLifecycleOptions = {}
): UseTaskLifecycleReturn {
  const { initialTaskId, onTaskCreated, onTaskStarted, onTaskFinished } =
    options;

  const [currentTaskId, setCurrentTaskId] = useState<string | null>(
    initialTaskId || null
  );

  // Use refs for callbacks to maintain stable references
  const onTaskCreatedRef = useRef(onTaskCreated);
  const onTaskStartedRef = useRef(onTaskStarted);
  const onTaskFinishedRef = useRef(onTaskFinished);

  // Update refs when callbacks change
  useEffect(() => {
    onTaskCreatedRef.current = onTaskCreated;
  }, [onTaskCreated]);

  useEffect(() => {
    onTaskStartedRef.current = onTaskStarted;
  }, [onTaskStarted]);

  useEffect(() => {
    onTaskFinishedRef.current = onTaskFinished;
  }, [onTaskFinished]);

  // Construct SSE URL
  const sseUrl = currentTaskId
    ? `/api/sse/agents/${agentId}/tasks/${currentTaskId}/events/stream`
    : null;

  return {
    currentTaskId,
    setCurrentTaskId,
    sseUrl,
    callbacks: {
      onTaskCreated: onTaskCreatedRef,
      onTaskStarted: onTaskStartedRef,
      onTaskFinished: onTaskFinishedRef,
    },
  };
}
