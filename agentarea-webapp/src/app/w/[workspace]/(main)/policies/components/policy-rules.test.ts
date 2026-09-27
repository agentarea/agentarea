import { describe, expect, it } from "vitest";
import type { PolicyDocument } from "@/types/policies";
import { documentToRules } from "./policy-rules";

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
