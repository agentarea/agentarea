import { describe, expect, it } from "vitest";
import { getTaskStatusPresentation } from "./status";

describe("task continuation status", () => {
  it("renders waiting_for_continuation as an actionable warning", () => {
    expect(getTaskStatusPresentation("waiting_for_continuation")).toEqual({
      label: "Continuation Required",
      labelKey: "continuationRequired",
      tone: "warning",
      pulse: true,
    });
  });
});
