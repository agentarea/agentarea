/**
 * Server-Sent Events (SSE) parsing utilities
 * Handles both buffered and unbuffered SSE stream parsing
 */

export interface SSEEvent {
  type: string;
  data: any;
}

export interface SSEParserOptions {
  /**
   * Callback invoked for each parsed SSE event
   */
  onEvent: (event: SSEEvent) => void;

  /**
   * Use buffered parsing approach (accumulates multiline data)
   * Default: true (recommended for production)
   */
  buffered?: boolean;
}

/**
 * Parses an SSE stream from a ReadableStream
 *
 * Supports standard SSE format:
 * - event: <event-type>
 * - data: <json-data>
 * - (blank line signals end of event)
 *
 * @param reader - ReadableStream reader from fetch response.body
 * @param options - Parser options including event callback
 *
 * @example
 * ```typescript
 * const response = await fetch('/api/events');
 * const reader = response.body.getReader();
 *
 * await parseSSEStream(reader, {
 *   onEvent: (event) => console.log(event),
 *   buffered: true
 * });
 * ```
 */
export async function parseSSEStream(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  options: SSEParserOptions
): Promise<void> {
  const { onEvent, buffered = true } = options;

  if (buffered) {
    await parseBufferedSSE(reader, onEvent);
  } else {
    await parseUnbufferedSSE(reader, onEvent);
  }
}

/**
 * Buffered SSE parsing - accumulates lines across chunks
 * Handles multiline data fields correctly
 */
async function parseBufferedSSE(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: SSEEvent) => void
): Promise<void> {
  const decoder = new TextDecoder();
  let textBuffer = "";
  let currentEventType: string | null = null;
  let currentDataLines: string[] = [];

  const processEvent = () => {
    if (currentDataLines.length === 0 && !currentEventType) {
      return;
    }

    const dataStr = currentDataLines.join("\n").trim();
    if (dataStr === "") {
      currentDataLines = [];
      currentEventType = null;
      return;
    }

    try {
      const parsed = JSON.parse(dataStr);
      const type = currentEventType || (parsed as any).type || "message";
      const data = (parsed as any).data ?? parsed;
      onEvent({ type, data });
    } catch (_err) {
      // Non-JSON payloads (e.g., heartbeats or [DONE])
      if (dataStr === "[DONE]" || dataStr.toLowerCase().includes("ping")) {
        // ignore heartbeats
      } else {
        onEvent({
          type: currentEventType || "message",
          data: { message: dataStr },
        });
      }
    }

    currentEventType = null;
    currentDataLines = [];
  };

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      textBuffer += decoder.decode(value, { stream: true });

      // Process complete lines; keep the last partial line in buffer
      const parts = textBuffer.split(/\r?\n/);
      textBuffer = parts.pop() || "";

      for (const rawLine of parts) {
        const line = rawLine;

        if (line === "") {
          // blank line denotes end of event
          processEvent();
          continue;
        }

        if (line.startsWith(":")) {
          // comment/heartbeat
          continue;
        }

        if (line.startsWith("event:")) {
          currentEventType = line.slice(6).trimStart();
          continue;
        }

        if (line.startsWith("data:")) {
          // support both 'data: ' and 'data:'
          const data = line.slice(5).trimStart();
          currentDataLines.push(data);
          continue;
        }

        // Fallback: treat as data continuation
        currentDataLines.push(line);
      }
    }

    // Flush any pending event on stream end
    processEvent();
  } finally {
    reader.releaseLock();
  }
}

/**
 * Unbuffered SSE parsing - simple line-by-line parsing
 * Faster but doesn't handle multiline data fields
 */
async function parseUnbufferedSSE(
  reader: ReadableStreamDefaultReader<Uint8Array>,
  onEvent: (event: SSEEvent) => void
): Promise<void> {
  const decoder = new TextDecoder();

  try {
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split("\n");

      for (const line of lines) {
        if (line.startsWith("data: ")) {
          try {
            const eventData = JSON.parse(line.slice(6));
            onEvent({
              type: eventData.type || "message",
              data: eventData.data || eventData,
            });
          } catch (parseError) {
            console.error("Failed to parse SSE event:", parseError);
          }
        }
      }
    }
  } finally {
    reader.releaseLock();
  }
}
