import type { PolicyDocument, PolicyRule } from "@/types/policies";

function fmtMoney(value: unknown): string {
  if (value === null || value === undefined) return "";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return `$${String(value)}`;
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

function fmtNum(value: number): string {
  return value.toLocaleString("en-US");
}

/**
 * Decompose a PolicyDocument into human-readable rules, one per active
 * restriction. An empty result means the document imposes no restrictions.
 */
export function documentToRules(doc: PolicyDocument | null | undefined): PolicyRule[] {
  if (!doc) return [];
  const rules: PolicyRule[] = [];

  const b = doc.budget;
  if (b) {
    if (b.monthly_spend_cap_usd != null)
      rules.push({ effect: "cap", category: "Budget", label: "Monthly spend cap", value: fmtMoney(b.monthly_spend_cap_usd) });
    if (b.run_budget_usd != null)
      rules.push({ effect: "cap", category: "Budget", label: "Per-run budget", value: fmtMoney(b.run_budget_usd) });
    if (b.service_budget_usd != null)
      rules.push({ effect: "cap", category: "Budget", label: "Per-service budget", value: fmtMoney(b.service_budget_usd) });
  }

  const t = doc.tokens;
  if (t) {
    if (t.max_tokens != null)
      rules.push({ effect: "cap", category: "Tokens", label: "Max tokens", value: fmtNum(t.max_tokens) });
    if (t.max_tokens_per_call != null)
      rules.push({ effect: "cap", category: "Tokens", label: "Max tokens per call", value: fmtNum(t.max_tokens_per_call) });
  }

  const tools = doc.tools;
  if (tools) {
    if (tools.allowed && tools.allowed.length > 0)
      rules.push({ effect: "allow", category: "Tools", label: "Allowed tools", value: tools.allowed.join(", ") });
    if (tools.denied && tools.denied.length > 0)
      rules.push({ effect: "deny", category: "Tools", label: "Denied tools", value: tools.denied.join(", ") });
  }

  const a = doc.approval;
  if (a?.requires_human_approval) {
    const approvers = a.approvers && a.approvers.length > 0 ? a.approvers.join(", ") : "any workspace member";
    rules.push({ effect: "approval", category: "Approval", label: "Requires human approval", value: `by ${approvers}` });
  }

  const cs = doc.content_safety;
  if (cs) {
    if (cs.prompt_injection_detection_enabled)
      rules.push({ effect: "safety", category: "Safety", label: "Prompt-injection detection", value: "on" });
    if (cs.output_sanitizer_enabled)
      rules.push({ effect: "safety", category: "Safety", label: "Output sanitizer", value: "on" });
  }

  return rules;
}

const SCOPE_LABELS: Record<string, string> = {
  workspace: "Workspace",
  agent: "Agent",
  task: "Task",
};

export function scopeLabel(scopeType: string, scopeId: string): string {
  const base = SCOPE_LABELS[scopeType] ?? scopeType;
  // Workspace-wide policies use the workspace id as scope_id; the label alone reads better.
  if (scopeType === "workspace") return base;
  return `${base} · ${scopeId}`;
}
