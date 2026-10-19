import { describe, expect, it } from "vitest";
import { summarizeToolGroup } from "./describeToolCall";

// The group summary was English prose, so a Russian page read "Ran 3 tools".
describe("summarizeToolGroup", () => {
  it("counts each category in order of first use, leaving the words to the caller", () => {
    expect(
      summarizeToolGroup(["read_file", "bash", "read_file", "multiply"])
    ).toEqual([
      { category: "read", count: 2 },
      { category: "ran", count: 1 },
      { category: "other", count: 1 },
    ]);
  });
});
