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

describe("a catalog install rule", () => {
  const install = (effect: "allow" | "deny", target: string): Policy =>
    ({
      id: "p1",
      subject_type: "workspace",
      subject_id: "w1",
      target,
      effect,
      params: {},
      enabled: true,
      priority: 0,
      condition: null,
    }) as Policy;

  it("reads as the registries it admits or refuses", () => {
    expect(
      policyToRule(install("deny", "registry_trust:community"))
    ).toMatchObject({
      category: "Catalog installs",
      label: "Deny installs",
      value: "from community registries",
    });
    expect(
      policyToRule(
        install("allow", "registry:0b6f8c1e-2a4d-4f7e-9a51-6d2c3b4a5e6f")
      )
    ).toMatchObject({
      label: "Allow installs",
      value: "from registry 0b6f8c1e-2a4d-4f7e-9a51-6d2c3b4a5e6f",
    });
    expect(policyToRule(install("deny", "registry:github"))).toMatchObject({
      label: "Deny installs",
      value: "from GitHub URLs",
    });
  });

  it("is not a tool rule nor custom in the matrix", () => {
    const matrix = policiesToMatrix(
      [install("deny", "registry_trust:community")],
      []
    );
    expect(matrix.customCount).toBe(0);
    expect(matrix.subjects[0].dimensions.tools.value).toBeNull();
  });
});
