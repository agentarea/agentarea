import { useCallback, useEffect, useRef, useState } from "react";

interface SSEEvent {
  type: string;
  data: unknown;
}

interface UseSSEOptions {
  onMessage?: (event: SSEEvent) => void;
  onError?: (error: Event) => void;
  onOpen?: () => void;
  onClose?: () => void;
  reconnect?: boolean;
  reconnectInterval?: number;
  headers?: Record<string, string>;
}

export function useSSE(url: string | null, options: UseSSEOptions = {}) {
  const [isConnected, setIsConnected] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const eventSourceRef = useRef<EventSource | null>(null);
  const reconnectTimeoutRef = useRef<NodeJS.Timeout | null>(null);
  const {
    onMessage,
    onError,
    onOpen,
    onClose,
    reconnect = true,
    reconnectInterval = 3000,
  } = options;

  // Keep latest callbacks in refs so connect/disconnect stay stable across renders
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;
  const onErrorRef = useRef(onError);
  onErrorRef.current = onError;
  const onOpenRef = useRef(onOpen);
  onOpenRef.current = onOpen;
  const onCloseRef = useRef(onClose);
  onCloseRef.current = onClose;

  const disconnect = useCallback(() => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    setIsConnected(false);
    onCloseRef.current?.();
  }, []);

  const connect = useCallback(() => {
    if (!url || eventSourceRef.current) return;

    try {
      const eventSource = new EventSource(url);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        setIsConnected(true);
        setError(null);
        onOpenRef.current?.();
      };

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          onMessageRef.current?.({ type: event.type || "message", data });
        } catch (e) {
          console.error("Failed to parse SSE message:", e);
        }
      };

      // Named SSE events use the backend's canonical PascalCase event_type as
      // the event name (see _format_sse_event / eventTypes.ts). Listening for
      // snake_case names here means none of these listeners ever fire, so live
      // events never reach the UI. Keep the snake_case system events (connected,
      // task_*) that really are emitted lowercase.
      const eventTypes = [
        "WorkflowStarted",
        "WorkflowCompleted",
        "WorkflowFailed",
        "WorkflowCancelled",
        "IterationStarted",
        "IterationCompleted",
        "LLMCallStarted",
        "LLMCallCompleted",
        "LLMCallFailed",
        "LLMCallChunk",
        "ToolCallStarted",
        "ToolCallCompleted",
        "ToolCallFailed",
        "HumanApprovalRequested",
        "HumanApprovalReceived",
        "HumanApprovalDenied",
        "ContextWarning",
        "ContextCompacted",
        "connected",
        "task_created",
        "task_completed",
        "task_failed",
        "error",
      ];

      eventTypes.forEach((eventType) => {
        eventSource.addEventListener(eventType, (event) => {
          // A native EventSource connection error is also dispatched as an
          // "error" event, but it is a plain Event with no `.data`. Don't try
          // to JSON.parse it (that yielded `"undefined" is not valid JSON`);
          // connection-level errors are handled by `onerror` below.
          const raw = (event as MessageEvent).data;
          if (raw == null) return;
          try {
            const data = JSON.parse(raw);
            onMessageRef.current?.({ type: eventType, data });
          } catch (e) {
            console.error(`Failed to parse ${eventType} event:`, e);
            // Try to send raw data if JSON parsing fails
            onMessageRef.current?.({ type: eventType, data: raw });
          }
        });
      });

      eventSource.onerror = (event) => {
        setIsConnected(false);
        setError("Connection error");
        onErrorRef.current?.(event);

        // Auto-reconnect if enabled
        if (reconnect && eventSource.readyState === EventSource.CLOSED) {
          reconnectTimeoutRef.current = setTimeout(() => {
            disconnect();
            connect();
          }, reconnectInterval);
        }
      };
    } catch (e) {
      setError(`Failed to connect: ${e}`);
      console.error("SSE connection error:", e);
    }
  }, [url, reconnect, reconnectInterval, disconnect]);

  useEffect(() => {
    if (url) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [url, connect, disconnect]);

  return {
    isConnected,
    error,
    connect,
    disconnect,
  };
}
