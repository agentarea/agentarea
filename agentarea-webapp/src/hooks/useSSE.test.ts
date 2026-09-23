// @vitest-environment jsdom

import { cleanup, renderHook } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { useSSE } from "./useSSE";

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

it("delivers canonical named interaction and execution events", () => {
  const source = Object.assign(new EventTarget(), { close: vi.fn() });
  vi.stubGlobal(
    "EventSource",
    vi.fn(function () {
      return source;
    })
  );
  const received: unknown[] = [];
  renderHook(() =>
    useSSE("/events", { onMessage: (event) => received.push(event) })
  );

  // Named events do not reach EventSource.onmessage in the browser.
  for (const type of [
    "input.request",
    "input.response",
    "a2ui.update.data",
    "execution.finished",
  ]) {
    source.dispatchEvent(
      new MessageEvent(type, { data: JSON.stringify({ event_type: type }) })
    );
  }
  expect(received).toEqual([
    { type: "input.request", data: { event_type: "input.request" } },
    { type: "input.response", data: { event_type: "input.response" } },
    { type: "a2ui.update.data", data: { event_type: "a2ui.update.data" } },
    { type: "execution.finished", data: { event_type: "execution.finished" } },
  ]);
});
