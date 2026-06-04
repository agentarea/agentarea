// Governance policy types — mirror the backend PolicyDocument / EffectivePolicy
// (agentarea-platform/libs/governance/.../domain/policies.py).

export type Money = string | number;

export interface BudgetPolicy {
  monthly_spend_cap_usd?: Money | null;
  run_budget_usd?: Money | null;
  service_budget_usd?: Money | null;
}

export interface TokenPolicy {
  max_tokens?: number | null;
  max_tokens_per_call?: number | null;
}

export interface ToolsPolicy {
  allowed?: string[] | null;
  denied?: string[];
}

export interface ApprovalPolicy {
  requires_human_approval?: boolean | null;
  escalation_rules?: string[];
  approvers?: string[];
}

export interface ContentSafetyPolicy {
  prompt_injection_detection_enabled?: boolean | null;
  output_sanitizer_enabled?: boolean | null;
}

export interface PolicyDocument {
  budget?: BudgetPolicy | null;
  tokens?: TokenPolicy | null;
  tools?: ToolsPolicy | null;
  approval?: ApprovalPolicy | null;
  content_safety?: ContentSafetyPolicy | null;
}

export interface EffectivePolicy extends PolicyDocument {
  source_policy_ids?: string[];
  resolver_version?: string;
}

export interface EffectivePolicyResponse {
  effective_policy: EffectivePolicy;
}

export interface GovernancePolicy {
  id: string;
  scope_type: string;
  scope_id: string;
  enabled: boolean;
  document: PolicyDocument;
}

// The effect axis from the unified-policy model.
export type PolicyEffect = "allow" | "cap" | "approval" | "deny" | "safety";

// A single human-readable rule decomposed from a PolicyDocument.
export interface PolicyRule {
  effect: PolicyEffect;
  category: string;
  label: string;
  value: string;
}
