import { describe, expect, it } from "vitest";
import { getTaskStatusPresentation } from "./status";

describe("tasks waiting on a person", () => {
  it("read as one 'Needs action' status whatever they wait for", () => {
    const presentations = [
      "waiting_for_input",
      "waiting_for_approval",
      "waiting_for_continuation",
      "blocked",
      "input_required",
    ].map(getTaskStatusPresentation);

    for (const presentation of presentations) {
      expect(presentation).toEqual({
        label: "Needs action",
        labelKey: "needsAction",
        kind: "attention",
      });
    }
  });
});
