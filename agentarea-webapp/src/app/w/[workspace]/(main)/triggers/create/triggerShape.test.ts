import { describe, expect, it } from "vitest";
import { requiresTaskText } from "./triggerShape";

describe("who has to state the task up front", () => {
  it("requires it of a schedule, which fires carrying nothing", () => {
    expect(requiresTaskText("cron")).toBe(true);
  });

  it("does not require it of a stream trigger, whose event comes attached", () => {
    expect(requiresTaskText("stream")).toBe(false);
  });

  it("asks for nothing before a type is chosen", () => {
    expect(requiresTaskText("")).toBe(false);
  });
});
