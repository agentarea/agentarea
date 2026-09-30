import { describe, expect, it } from "vitest";
import { getTaskStatusPresentation } from "./status";

describe("task continuation status", () => {
  it("renders waiting_for_continuation as waiting on a person", () => {
    expect(getTaskStatusPresentation("waiting_for_continuation")).toEqual({
      label: "Continuation Required",
      labelKey: "continuationRequired",
      kind: "attention",
    });
  });
});
