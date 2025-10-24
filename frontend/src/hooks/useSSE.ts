import { useEffect, useRef, useState } from "react";

interface SSEEvent {
  type: string;
  data: any;
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

  const connect = () => {
    if (!url || eventSourceRef.current) return;

    try {
      const eventSource = new EventSource(url);
      eventSourceRef.current = eventSource;

      eventSource.onopen = () => {
        setIsConnected(true);
        setError(null);
        onOpen?.();
      };

      eventSource.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data);
          onMessage?.({ type: event.type || "message", data });
        } catch (e) {
          console.error("Failed to parse SSE message:", e);
        }
      };

      // Handle custom event types - updated to match our workflow events
      const eventTypes = [
        "task_completed",
        "task_failed",
        "workflow_completed",
        "workflow_failed",
        "workflow_started",
        "iteration_started",
        "iteration_completed",
        "llm_call_started",
        "llm_call_completed",
        "llm_call_failed",
        "tool_call_started",
        "tool_call_completed",
        "tool_call_failed",
        "budget_warning",
        "budget_exceeded",
        "human_approval_requested",
        "human_approval_received",
        "connected",
        "error",
      ];

      eventTypes.forEach((eventType) => {
        eventSource.addEventListener(eventType, (event) => {
          try {
            const data = JSON.parse((event as MessageEvent).data);
            onMessage?.({ type: eventType, data });
          } catch (e) {
            console.error(`Failed to parse ${eventType} event:`, e);
            // Try to send raw data if JSON parsing fails
            onMessage?.({
              type: eventType,
              data: (event as MessageEvent).data,
            });
          }
        });
      });

      eventSource.onerror = (event) => {
        setIsConnected(false);
        setError("Connection error");
        onError?.(event);

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
  };

  const disconnect = () => {
    if (reconnectTimeoutRef.current) {
      clearTimeout(reconnectTimeoutRef.current);
      reconnectTimeoutRef.current = null;
    }

    if (eventSourceRef.current) {
      eventSourceRef.current.close();
      eventSourceRef.current = null;
    }

    setIsConnected(false);
    onClose?.();
  };

  useEffect(() => {
    if (url) {
      connect();
    }

    return () => {
      disconnect();
    };
  }, [url]);

  return {
    isConnected,
    error,
    connect,
    disconnect,
  };
}
