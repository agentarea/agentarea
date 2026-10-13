import { describe, expect, it } from "vitest";
import type { Policy, PolicyDocument } from "@/types/policies";
import { documentToRules, policiesToMatrix, policyToRule } from "./policy-rules";

describe("documentToRules", () => {
  it("formats a valid budget cap in the given currency/locale", () => {
    const doc: PolicyDocument = {
      budget: { monthly_spend_cap_usd: 100 },
    };
    const [rule] = documentToRules(doc, "USD", "en-US");
    expect(rule.label).toBe("Monthly budget");
    expect(rule.value).toBe("$100");
  });

  it("surfaces a malformed budget value as raw text instead of $0.00", () => {
    // A non-numeric string is still a valid `Money` at the type level
    // (Money = string | number) — the backend should never send this, but
    // the UI must not silently show a formatted zero for it.
    const doc: PolicyDocument = {
      budget: { monthly_spend_cap_usd: "not-a-number" },
    };
    const [rule] = documentToRules(doc, "USD", "en-US");
    expect(rule.value).toBe("not-a-number");
  });
});

describe("a spend cap on one kind of spend", () => {
  const cap = (params: Record<string, unknown>): Policy =>
    ({
      id: "p1",
      subject_type: "agent",
      subject_id: "a1",
      target: "spend",
      effect: "cap",
      params,
      enabled: true,
    }) as Policy;

  it("names the kind it counts", () => {
    expect(
      policyToRule(cap({ amount_usd: "2", period: "run", category: "llm" }))
        .label
    ).toBe("Per-task LLM budget");
    expect(
      policyToRule(cap({ amount_usd: "2", category: "tools" })).label
    ).toBe("Monthly tools budget");
  });

  it("marks the kind on the matrix chip", () => {
    const matrix = policiesToMatrix(
      [cap({ amount_usd: "2", period: "run", category: "tools" })],
      [{ id: "a1", name: "Agent" }],
      "USD",
      "en-US"
    );
    expect(matrix.subjects[0].dimensions.budget.value).toBe("$2/run·tools");
  });
});
