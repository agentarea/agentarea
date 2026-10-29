import type { EffectivePolicy } from "@/api/client/types.gen";
import type { PolicyEffect } from "@/types/policies";

export type EffectiveGuardrails = {
  /** Policies (workspace and agent) merged into the effective policy. */
  sources: number;
  effectCounts: Partial<Record<PolicyEffect, number>>;
};

const isSet = (value: unknown) => value !== null && value !== undefined;

/**
 * Summarises the merged policy an agent runs under by effect, so the overview
 * reports what applies to the agent rather than only rules aimed at it.
 */
export function summarizeEffectivePolicy(
  policy: EffectivePolicy
): EffectiveGuardrails {
  const { tools, approval, budget, tokens, execution, content_safety } = policy;

  const caps = [
    budget?.agent_monthly_spend_cap_usd,
    budget?.monthly_spend_cap_usd,
    budget?.run_budget_usd,
    budget?.service_budget_usd,
    tokens?.max_tokens,
    tokens?.max_tokens_per_call,
    execution?.max_model_turns,
    execution?.max_tool_calls_per_turn,
    execution?.max_tool_calls_total,
  ].filter(isSet).length + (budget?.spend_caps?.length ?? 0);

  const counts: Record<PolicyEffect, number> = {
    deny: tools?.denied?.length ?? 0,
    approval: approval?.requires_human_approval
      ? 1
      : (approval?.escalation_rules?.length ?? 0),
    cap: caps,
    allow: tools?.allowed?.length ?? 0,
    safety: [
      content_safety?.output_sanitizer_enabled,
      content_safety?.prompt_injection_detection_enabled,
      content_safety?.answer_check?.enabled,
    ].filter(Boolean).length,
  };

  const effectCounts: Partial<Record<PolicyEffect, number>> = {};
  for (const effect of Object.keys(counts) as PolicyEffect[]) {
    if (counts[effect] > 0) effectCounts[effect] = counts[effect];
  }
  return { sources: policy.source_policy_ids?.length ?? 0, effectCounts };
}
