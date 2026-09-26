import { describe, expect, it } from "vitest";
import { extractInboxResult, getInboxResultDetails } from "./inboxResult";

describe("extractInboxResult", () => {
  it("extracts the human response from an SEO result envelope", () => {
    const result = extractInboxResult({
      response: "SEO review blocked: no PR URL was provided.",
      validation_state: "passed",
      total_cost: "0.0037046",
      own_cost: "0.0037046",
    });

    expect(result).toEqual({
      kind: "text",
      content: "SEO review blocked: no PR URL was provided.",
    });
    expect(result.content).not.toContain("validation_state");
    expect(result.content).not.toContain("total_cost");
  });

  it("passes a plain string through as assistant content", () => {
    expect(extractInboxResult("## Review\n\nLooks good.")).toEqual({
      kind: "text",
      content: "## Review\n\nLooks good.",
    });
  });

  it("treats null and empty results as empty", () => {
    expect(extractInboxResult(null)).toEqual({ kind: "empty", content: null });
    expect(extractInboxResult({})).toEqual({ kind: "empty", content: null });
    expect(extractInboxResult("")).toEqual({ kind: "empty", content: null });
  });

  it("keeps an unknown structured result available for disclosure", () => {
    const value = { output: ["one", "two"], metadata: { source: "agent" } };
    expect(extractInboxResult(value)).toEqual({
      kind: "structured",
      content: JSON.stringify(value, null, 2),
      value,
    });
  });

  it("does not treat a non-string response field as a human response", () => {
    const value = { response: { text: "nested" }, state: "unknown" };
    expect(extractInboxResult(value).kind).toBe("structured");
  });

  it("treats an accounting-only envelope as empty", () => {
    expect(
      extractInboxResult({ total_cost: "0", own_cost: "0" })
    ).toEqual({ kind: "empty", content: null });
    expect(
      extractInboxResult({
        total_cost: "0.0012",
        own_cost: "0.0012",
        total_tokens: 840,
        total_tool_calls: 3,
      })
    ).toEqual({ kind: "empty", content: null });
  });

  it("strips accounting fields from a disclosed structured result", () => {
    const view = extractInboxResult({
      output: ["one"],
      total_cost: "0.5",
      own_cost: "0.5",
    });

    expect(view.kind).toBe("structured");
    expect(view.content).not.toContain("total_cost");
    expect(view.content).toContain("output");
  });
});

describe("getInboxResultDetails", () => {
  it("omits accounting fields so a cost-only envelope discloses nothing", () => {
    expect(
      getInboxResultDetails({
        response: "Done.",
        total_cost: "0",
        own_cost: "0",
      })
    ).toBeNull();
  });

  it("keeps non-accounting envelope fields", () => {
    expect(
      getInboxResultDetails({
        response: "Done.",
        validation_state: "passed",
        total_cost: "0",
      })
    ).toEqual({ validation_state: "passed" });
  });
});
