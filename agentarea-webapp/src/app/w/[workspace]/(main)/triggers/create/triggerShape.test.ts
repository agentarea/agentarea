import { describe, expect, it } from "vitest";
import { requiresTaskText, triggerShape } from "./triggerShape";

describe("who has to state the task up front", () => {
  it("requires it of a schedule, which fires carrying nothing", () => {
    expect(requiresTaskText("cron")).toBe(true);
  });

  it("does not require it of a webhook, whose text arrives with the call", () => {
    expect(requiresTaskText("webhook")).toBe(false);
  });

  it("does not require it of a poller, which works on what it finds", () => {
    expect(requiresTaskText("cron", "imap")).toBe(false);
  });

  it("asks for nothing before a type is chosen", () => {
    expect(requiresTaskText("")).toBe(false);
  });
});

describe("whether the form is editing a channel", () => {
  it("reads a channel off the catalog entry", () => {
    expect(
      triggerShape({ selected: { kind: "messaging", backend_type: "webhook" } })
        .isChannel
    ).toBe(true);
  });

  it("falls back to the extractor for a saved channel with no catalog yet", () => {
    expect(
      triggerShape({
        initialData: { trigger_type: "webhook", data_extractor: "telegram" },
      }).isChannel
    ).toBe(true);
  });

  it("leaves a plain webhook alone, so it keeps its events and methods", () => {
    expect(
      triggerShape({ initialData: { trigger_type: "webhook" } }).isChannel
    ).toBe(false);
    expect(
      triggerShape({ selected: { kind: "event", backend_type: "webhook" } })
        .isChannel
    ).toBe(false);
  });

  it("never calls a schedule a channel, extractor or not", () => {
    expect(
      triggerShape({
        initialData: { trigger_type: "cron", data_extractor: "imap" },
      }).isChannel
    ).toBe(false);
  });
});
