// Governance policy types.
//
// The backend uses a UNIFIED rule model: a policy is a single rule
// (/v1/policies). The old typed PolicyDocument GET/PUT endpoints are gone.
// PolicyDocument / EffectivePolicy survive only for the workspace baseline,
// which still comes from POST /v1/governance/effective-policy/preview.

import type { RegistryResponse } from "@/api/client/types.gen";
import { zRegistryResponse } from "@/api/client/zod.gen";

export type Money = string | number;

export interface BudgetPolicy {
  monthly_spend_cap_usd?: Money | null;
  agent_monthly_spend_cap_usd?: Money | null;
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

// --- unified rule model ---------------------------------------------------

// The effect axis from the unified-policy model.
export type PolicyEffect = "allow" | "cap" | "approval" | "deny" | "safety";

// Who a policy rule applies to.
export type PolicySubjectType = "workspace" | "agent" | "user" | "group";

// A single policy rule as returned by /v1/policies. `target` is a selector
// string ("tool:send_email" | "tool:*" | "spend" | "service" | "tokens" |
// "content" | "*" | "mcp:github" | "model:*"). `params` are effect-specific.
export interface Policy {
  id: string;
  enabled: boolean;
  priority: number;
  subject_type: PolicySubjectType;
  subject_id: string;
  target: string;
  effect: PolicyEffect;
  params: Record<string, unknown>;
  condition: string | null;
}

// Body for POST /v1/policies and PATCH /v1/policies/{id} (partial on PATCH).
export interface PolicyCreate {
  subject_type: PolicySubjectType;
  subject_id: string;
  target: string;
  effect: PolicyEffect;
  params?: Record<string, unknown>;
  condition?: string | null;
  enabled?: boolean;
  priority?: number;
}

export type PolicyUpdate = Partial<PolicyCreate>;

// --- selector helpers -----------------------------------------------------

// A target is a tool selector when it is "tool:<name>" (or "tool:*").
export function isToolTarget(target: string): boolean {
  return target.startsWith("tool:");
}

// Strip the "tool:" prefix, returning the tool name (or "*").
export function toolNameFromTarget(target: string): string {
  return target.slice("tool:".length);
}

export function toolTarget(name: string): string {
  return `tool:${name}`;
}

// Known, dimension-mapped targets for cap/safety effects.
export const CAP_TARGETS = ["spend", "service", "tokens"] as const;
export type CapTarget = (typeof CAP_TARGETS)[number];

export function isCapTarget(target: string): target is CapTarget {
  return (CAP_TARGETS as readonly string[]).includes(target);
}

// --- catalog install targets (ADR-0044) ----------------------------------

// Allow/deny rules on these decide which registries a workspace (or a user)
// may install catalog items from: `registry:<id>` names one registry (or
// `registry:github`, a direct GitHub import), `registry_trust:<level>` every
// registry of a trust level.
export type RegistryTrustLevel = RegistryResponse["trust"];

export const REGISTRY_TRUST_LEVELS: readonly RegistryTrustLevel[] =
  zRegistryResponse.shape.trust.options;

export type InstallTarget =
  | { kind: "registry"; registryId: string }
  | { kind: "registry_trust"; trust: RegistryTrustLevel };

export function registryTarget(registryId: string): string {
  return `registry:${registryId}`;
}

export function registryTrustTarget(trust: RegistryTrustLevel): string {
  return `registry_trust:${trust}`;
}

// A skill imported straight from a GitHub URL passed through no registry; install
// rules name that source as this pseudo-registry, of trust "community"
// (GITHUB_IMPORT_REGISTRY_ID in agentarea_common.constants).
export const GITHUB_IMPORT_REGISTRY_ID = "github";
export const GITHUB_IMPORT_TRUST: RegistryTrustLevel = "community";

export function parseInstallTarget(target: string): InstallTarget | null {
  const [kind, value] = target.split(":", 2);
  if (!value) return null;
  if (kind === "registry") return { kind, registryId: value };
  if (kind === "registry_trust") {
    const trust = REGISTRY_TRUST_LEVELS.find((level) => level === value);
    return trust ? { kind, trust } : null;
  }
  return null;
}

export function isInstallTarget(target: string): boolean {
  return parseInstallTarget(target) !== null;
}

// --- decomposed UI rule (drawer list / baseline) --------------------------

// A single human-readable rule shown in the drawer / baseline strip. For real
// policies `id` is the backing rule id (used to edit/delete); the baseline is
// derived from the previewed EffectivePolicy and has no id.
export interface PolicyRule {
  id?: string;
  effect: PolicyEffect;
  category: string;
  label: string;
  value: string;
  // Enforcement stage label, derived from the rule kind. Mirrors the
  // governance engine's enforcement phases (PRE_LLM_CALL, PRE_TOOL_CALL, …).
  stage: string;
  enabled?: boolean;
}
