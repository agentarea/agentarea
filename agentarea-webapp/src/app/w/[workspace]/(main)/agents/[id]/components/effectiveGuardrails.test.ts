import { describe, expect, it } from "vitest";
import { summarizeEffectivePolicy } from "./effectiveGuardrails";

describe("summarizeEffectivePolicy", () => {
  it("reports nothing for an empty policy", () => {
    expect(summarizeEffectivePolicy({})).toEqual({
      sources: 0,
      effectCounts: {},
    });
  });

  it("counts workspace and agent rules merged into one policy", () => {
    const summary = summarizeEffectivePolicy({
      source_policy_ids: ["ws-policy", "agent-policy"],
      tools: { denied: ["mcp:github:delete_repo", "tool:shell"], allowed: null },
      approval: { escalation_rules: ["mcp:stripe:refund"] },
      budget: {
        monthly_spend_cap_usd: "100",
        run_budget_usd: null,
        spend_caps: [{} as never],
      },
      tokens: { max_tokens: 50000 },
      content_safety: {
        prompt_injection_detection_enabled: true,
        answer_check: { enabled: true },
      },
    });

    expect(summary).toEqual({
      sources: 2,
      effectCounts: { deny: 2, approval: 1, cap: 3, safety: 2 },
    });
  });

  it("treats approval on every call as one rule", () => {
    const summary = summarizeEffectivePolicy({
      approval: {
        requires_human_approval: true,
        escalation_rules: ["a", "b"],
      },
    });
    expect(summary.effectCounts).toEqual({ approval: 1 });
  });

  it("separates no allowlist from an empty allowlist", () => {
    expect(
      summarizeEffectivePolicy({ tools: { allowed: null } }).effectCounts
    ).toEqual({});
    expect(
      summarizeEffectivePolicy({ tools: { allowed: ["tool:search"] } })
        .effectCounts
    ).toEqual({ allow: 1 });
  });
});
