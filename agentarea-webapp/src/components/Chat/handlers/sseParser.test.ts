import { describe, expect, it } from "vitest";
import { parseSSEStream, type SSEEvent } from "./sseParser";

function readerOf(...chunks: string[]): ReadableStreamDefaultReader<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream<Uint8Array>({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  }).getReader();
}

async function parse(...chunks: string[]): Promise<SSEEvent[]> {
  const events: SSEEvent[] = [];
  await parseSSEStream(readerOf(...chunks), {
    onEvent: (event) => events.push(event),
  });
  return events;
}

describe("parseSSEStream", () => {
  // The task feed stamps every stored entry with its log seq as the SSE id.
  it("keeps the id field out of the data and hands it to the caller", async () => {
    const events = await parse(
      'id: 12\nevent: task.completed\ndata: {"event_type": "task.completed", "data": {"result": "hi"}}\n\n'
    );

    expect(events).toEqual([
      { type: "task.completed", id: "12", data: { result: "hi" } },
    ]);
  });

  it("leaves the id unset on live-only events that carry none", async () => {
    const events = await parse(
      'event: llm.call.chunk\ndata: {"data": {"chunk": "h"}}\n\n'
    );

    expect(events).toEqual([{ type: "llm.call.chunk", data: { chunk: "h" } }]);
  });

  it("joins an event split across chunks", async () => {
    const events = await parse(
      "id: 3\nevent: llm.call.completed\nda",
      'ta: {"data": {"content": "ok"}}\n\n'
    );

    expect(events).toEqual([
      { type: "llm.call.completed", id: "3", data: { content: "ok" } },
    ]);
  });

  it("ignores retry and comment lines", async () => {
    const events = await parse(
      ': keepalive\nretry: 5000\nevent: task.started\ndata: {"data": {}}\n\n'
    );

    expect(events).toEqual([{ type: "task.started", data: {} }]);
  });
});
