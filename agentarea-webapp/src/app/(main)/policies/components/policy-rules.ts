import type {
  Policy,
  PolicyDocument,
  PolicyEffect,
  PolicyRule,
} from "@/types/policies";
import {
  isCapTarget,
  isToolTarget,
  toolNameFromTarget,
} from "@/types/policies";

// Enforcement-stage labels, grounded in the governance engine's phases
// (PRE_LLM_CALL, POST_LLM_CALL, PRE_TOOL_CALL, TOOL_DISCOVERY, …). The phase is
// implied by the rule kind, so we attach it where each rule is decomposed.
const STAGE = {
  beforeLlmOrTool: "Before LLM / tool call",
  beforeLlm: "Before LLM call",
  beforeTool: "Before tool call",
  toolDiscovery: "Tool discovery",
  sensitiveAction: "Before sensitive action",
  llmInput: "On LLM input",
  llmOutput: "On LLM output",
  custom: "Custom enforcement",
} as const;

function fmtMoney(value: unknown): string {
  if (value === null || value === undefined) return "";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return `$${String(value)}`;
  return `$${n.toLocaleString("en-US", { maximumFractionDigits: 2 })}`;
}

function fmtNum(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  return n.toLocaleString("en-US");
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function fmtCustomValue(value: unknown): string {
  if (value === null || value === undefined) return "—";
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean")
    return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function str(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return undefined;
}

/**
 * Decompose a PolicyDocument into human-readable rules, one per active
 * restriction. Used only for the workspace baseline, which still comes from the
 * previewed EffectivePolicy. An empty result means no restrictions.
 */
export function documentToRules(
  doc: PolicyDocument | null | undefined
): PolicyRule[] {
  if (!doc) return [];
  const rules: PolicyRule[] = [];

  const b = doc.budget;
  if (b) {
    if (b.monthly_spend_cap_usd != null)
      rules.push({ effect: "cap", category: "Budget", label: "Monthly spend cap", value: fmtMoney(b.monthly_spend_cap_usd), stage: STAGE.beforeLlmOrTool });
    if (b.run_budget_usd != null)
      rules.push({ effect: "cap", category: "Budget", label: "Per-run budget", value: fmtMoney(b.run_budget_usd), stage: STAGE.beforeLlmOrTool });
    if (b.service_budget_usd != null)
      rules.push({ effect: "cap", category: "Budget", label: "Per-service budget", value: fmtMoney(b.service_budget_usd), stage: STAGE.beforeLlmOrTool });
  }

  const t = doc.tokens;
  if (t) {
    if (t.max_tokens != null)
      rules.push({ effect: "cap", category: "Tokens", label: "Max tokens", value: fmtNum(t.max_tokens), stage: STAGE.beforeLlm });
    if (t.max_tokens_per_call != null)
      rules.push({ effect: "cap", category: "Tokens", label: "Max tokens per call", value: fmtNum(t.max_tokens_per_call), stage: STAGE.beforeLlm });
  }

  const tools = doc.tools;
  if (tools) {
    if (tools.allowed && tools.allowed.length > 0)
      rules.push({ effect: "allow", category: "Tools", label: "Allowed tools", value: tools.allowed.join(", "), stage: STAGE.toolDiscovery });
    if (tools.denied && tools.denied.length > 0)
      rules.push({ effect: "deny", category: "Tools", label: "Denied tools", value: tools.denied.join(", "), stage: STAGE.beforeTool });
  }

  const a = doc.approval;
  if (a?.requires_human_approval) {
    const approvers = a.approvers && a.approvers.length > 0 ? a.approvers.join(", ") : "any workspace member";
    rules.push({ effect: "approval", category: "Approval", label: "Requires human approval", value: `by ${approvers}`, stage: STAGE.sensitiveAction });
  }

  const cs = doc.content_safety;
  if (cs) {
    if (cs.prompt_injection_detection_enabled)
      rules.push({ effect: "safety", category: "Safety", label: "Prompt-injection detection", value: "on", stage: STAGE.llmInput });
    if (cs.output_sanitizer_enabled)
      rules.push({ effect: "safety", category: "Safety", label: "Output sanitizer", value: "on", stage: STAGE.llmOutput });
  }

  return rules;
}

const SCOPE_LABELS: Record<string, string> = {
  workspace: "Workspace",
  agent: "Agent",
  user: "User",
  group: "Group",
  task: "Task",
};

export function scopeLabel(scopeType: string, scopeId: string): string {
  const base = SCOPE_LABELS[scopeType] ?? scopeType;
  // Workspace-wide policies use the workspace id as subject_id; the label
  // alone reads better.
  if (scopeType === "workspace") return base;
  return `${base} · ${scopeId}`;
}

interface AgentLike {
  id: string;
  name: string;
}

// --- single rule → UI row -------------------------------------------------

// Which matrix dimension a rule maps to, or "custom" when it doesn't map.
export type MatrixDimensionKey =
  | "budget"
  | "tokens"
  | "tools"
  | "approval"
  | "safety"
  | "custom";

// Classify a rule by effect + target into a matrix dimension. Anything that
// isn't a known mapping (or carries a CEL condition) is "custom".
export function ruleDimension(policy: Policy): MatrixDimensionKey {
  if (policy.condition) return "custom";
  const { effect, target } = policy;

  if (effect === "cap") {
    if (target === "spend" || target === "service") return "budget";
    if (target === "tokens") return "tokens";
    return "custom";
  }
  if (effect === "safety") {
    return target === "content" ? "safety" : "custom";
  }
  if (effect === "approval") {
    if (target === "*" || isToolTarget(target)) return "approval";
    return "custom";
  }
  if (effect === "deny" || effect === "allow") {
    if (isToolTarget(target)) return "tools";
    return "custom";
  }
  return "custom";
}

// Human-readable category for a rule, by dimension.
const CATEGORY_BY_DIMENSION: Record<MatrixDimensionKey, string> = {
  budget: "Budget",
  tokens: "Tokens",
  tools: "Tools",
  approval: "Approval",
  safety: "Safety",
  custom: "Custom",
};

const STAGE_BY_DIMENSION: Record<MatrixDimensionKey, string> = {
  budget: STAGE.beforeLlmOrTool,
  tokens: STAGE.beforeLlm,
  tools: STAGE.beforeTool,
  approval: STAGE.sensitiveAction,
  safety: STAGE.llmInput,
  custom: STAGE.custom,
};

// Build a human-readable label + value for a single rule.
function describeRule(policy: Policy, dimension: MatrixDimensionKey): {
  label: string;
  value: string;
} {
  const p = isPlainObject(policy.params) ? policy.params : {};

  if (dimension === "budget") {
    const amount = fmtMoney(p.amount_usd);
    if (policy.target === "spend") {
      const period = str(p.period);
      const label = period === "run" ? "Per-run budget" : "Monthly spend cap";
      return { label, value: amount };
    }
    return { label: "Per-service budget", value: amount };
  }

  if (dimension === "tokens") {
    const max = p.max_tokens;
    const perCall = p.max_tokens_per_call;
    if (max != null && perCall != null)
      return {
        label: "Token caps",
        value: `${fmtNum(max)} total · ${fmtNum(perCall)}/call`,
      };
    if (perCall != null)
      return { label: "Max tokens per call", value: fmtNum(perCall) };
    if (max != null) return { label: "Max tokens", value: fmtNum(max) };
    return { label: "Token cap", value: "set" };
  }

  if (dimension === "tools") {
    const name = toolNameFromTarget(policy.target);
    const verb = policy.effect === "deny" ? "Deny" : "Allow";
    return {
      label: `${verb} tool`,
      value: name === "*" ? "all tools" : name,
    };
  }

  if (dimension === "approval") {
    const approvers = Array.isArray(p.approvers)
      ? (p.approvers as unknown[]).map(String).filter(Boolean)
      : [];
    const by =
      approvers.length > 0 ? approvers.join(", ") : "any workspace member";
    if (policy.target === "*")
      return { label: "Approval for all actions", value: `by ${by}` };
    const name = toolNameFromTarget(policy.target);
    return {
      label: `Approval for ${name === "*" ? "all tools" : name}`,
      value: `by ${by}`,
    };
  }

  if (dimension === "safety") {
    const parts: string[] = [];
    if (p.prompt_injection) parts.push("prompt-injection");
    if (p.output_sanitizer) parts.push("output sanitizer");
    return {
      label: "Content safety",
      value: parts.length > 0 ? parts.join(", ") : "on",
    };
  }

  // Custom — render generically, never crash.
  const valueParts: string[] = [];
  if (policy.condition) valueParts.push(`when ${policy.condition}`);
  if (Object.keys(p).length > 0) valueParts.push(fmtCustomValue(p));
  return {
    label: `${policy.effect} · ${policy.target}`,
    value: valueParts.length > 0 ? valueParts.join(" · ") : policy.target,
  };
}

// Decompose a single backend Policy into the UI rule row shown in the drawer.
export function policyToRule(policy: Policy): PolicyRule {
  const dimension = ruleDimension(policy);
  const { label, value } = describeRule(policy, dimension);
  return {
    id: policy.id,
    effect: policy.effect,
    category: CATEGORY_BY_DIMENSION[dimension],
    label,
    value,
    stage: STAGE_BY_DIMENSION[dimension],
    enabled: policy.enabled,
  };
}

// --- subject-centric control matrix ---------------------------------------

// One control dimension's compact summary for a subject. `value` is the chip
// text (null when the subject sets nothing for this dimension); `effect` maps
// to the shared EFFECT_STYLES palette so the cell colors consistently.
export interface MatrixDimension {
  value: string | null;
  effect: PolicyEffect | null;
}

export interface MatrixDimensions {
  budget: MatrixDimension;
  tokens: MatrixDimension;
  tools: MatrixDimension;
  approval: MatrixDimension;
  safety: MatrixDimension;
}

export interface MatrixSubject {
  subjectKey: string;
  subjectType: "workspace" | "agent";
  subjectId: string;
  subjectName: string;
  enabled: boolean;
  dimensions: MatrixDimensions;
  customCount: number;
  // Every enabled-or-not backend rule for this subject, decomposed for the
  // drawer. Each carries its backing rule id so the drawer can edit/delete.
  rules: PolicyRule[];
  // Whether the subject has any active (enabled) rule.
  hasActiveRule: boolean;
}

export interface PolicyMatrix {
  subjects: MatrixSubject[];
  // Risk-strip stats computed across all subjects + the full agent list.
  governedCount: number;
  noBudgetCapCount: number;
  noApprovalCount: number;
  ungovernedAgentCount: number;
  customCount: number;
}

function fmtBudgetCompact(value: unknown): string {
  if (value === null || value === undefined) return "";
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  // Whole dollars without cents read cleaner for caps like "$100".
  return Number.isInteger(n)
    ? `$${n.toLocaleString("en-US")}`
    : `$${n.toLocaleString("en-US", {
        minimumFractionDigits: 2,
        maximumFractionDigits: 2,
      })}`;
}

function fmtTokensCompact(value: unknown): string {
  const n = typeof value === "number" ? value : Number(value);
  if (Number.isNaN(n)) return String(value);
  if (n >= 1000) {
    const k = n / 1000;
    return `${Number.isInteger(k) ? k : k.toFixed(1)}k`;
  }
  return String(n);
}

const NO_DIMENSION: MatrixDimension = { value: null, effect: null };

function emptyDimensions(): MatrixDimensions {
  return {
    budget: { ...NO_DIMENSION },
    tokens: { ...NO_DIMENSION },
    tools: { ...NO_DIMENSION },
    approval: { ...NO_DIMENSION },
    safety: { ...NO_DIMENSION },
  };
}

// Roll a subject's rules up into the compact dimension cells. Only enabled
// rules contribute to the at-a-glance cells; disabled rules still appear in the
// drawer (via `rules`). Resilient to malformed params — never throws.
function buildDimensions(rules: Policy[]): {
  dimensions: MatrixDimensions;
  customCount: number;
} {
  const dims = emptyDimensions();
  let customCount = 0;

  const budgetParts: string[] = [];
  let denyToolCount = 0;
  let allowToolCount = 0;
  let approvalAll = false;
  let approvalToolCount = 0;
  let safetyInput = false;
  let safetyOutput = false;
  let safetyOn = false;

  for (const policy of rules) {
    const dimension = ruleDimension(policy);
    if (dimension === "custom") {
      customCount += 1;
      continue;
    }
    const p = isPlainObject(policy.params) ? policy.params : {};

    if (dimension === "budget") {
      if (policy.target === "spend") {
        const period = str(p.period);
        budgetParts.push(
          `${fmtBudgetCompact(p.amount_usd)}/${period === "run" ? "run" : "mo"}`
        );
      } else {
        budgetParts.push(`${fmtBudgetCompact(p.amount_usd)}/svc`);
      }
    } else if (dimension === "tokens") {
      const max = p.max_tokens ?? p.max_tokens_per_call;
      if (max != null)
        dims.tokens = { value: fmtTokensCompact(max), effect: "cap" };
      else dims.tokens = { value: "set", effect: "cap" };
    } else if (dimension === "tools") {
      if (policy.effect === "deny") denyToolCount += 1;
      else allowToolCount += 1;
    } else if (dimension === "approval") {
      if (policy.target === "*") approvalAll = true;
      else approvalToolCount += 1;
    } else if (dimension === "safety") {
      if (p.prompt_injection) safetyInput = true;
      if (p.output_sanitizer) safetyOutput = true;
      if (!p.prompt_injection && !p.output_sanitizer) safetyOn = true;
    }
  }

  if (budgetParts.length > 0) {
    const [primary, ...rest] = budgetParts;
    dims.budget = {
      value: rest.length > 0 ? `${primary} +${rest.length}` : primary,
      effect: "cap",
    };
  }

  if (denyToolCount > 0) {
    dims.tools = { value: `${denyToolCount} denied`, effect: "deny" };
  } else if (allowToolCount > 0) {
    dims.tools = { value: `${allowToolCount} allowed`, effect: "allow" };
  }

  if (approvalAll) {
    dims.approval = { value: "required", effect: "approval" };
  } else if (approvalToolCount > 0) {
    dims.approval = {
      value: `${approvalToolCount} tool${approvalToolCount === 1 ? "" : "s"}`,
      effect: "approval",
    };
  }

  if (safetyInput && safetyOutput) dims.safety = { value: "on", effect: "safety" };
  else if (safetyInput) dims.safety = { value: "input", effect: "safety" };
  else if (safetyOutput) dims.safety = { value: "output", effect: "safety" };
  else if (safetyOn) dims.safety = { value: "on", effect: "safety" };

  return { dimensions: dims, customCount };
}

const WORKSPACE_SUBJECT_KEY = "__workspace__";

/**
 * Build the subject-centric control matrix from RULES. Rules are grouped by
 * subject (subject_type + subject_id); agent names are resolved from the agent
 * list. The workspace subject (if any workspace rules exist) leads as a single
 * inherited-by-all-agents row; other subjects follow. Risk-strip stats are
 * computed against the full agent list. Resilient to malformed rules — never
 * throws.
 */
export function policiesToMatrix(
  policies: Policy[],
  agents: AgentLike[]
): PolicyMatrix {
  const agentNameById = new Map(agents.map((a) => [a.id, a.name]));

  // Group rules by subject. Workspace rules collapse into a single subject;
  // others key on type+id.
  const groups = new Map<
    string,
    { type: Policy["subject_type"]; id: string; rules: Policy[] }
  >();

  for (const policy of policies) {
    const key =
      policy.subject_type === "workspace"
        ? WORKSPACE_SUBJECT_KEY
        : `${policy.subject_type}:${policy.subject_id}`;
    const existing = groups.get(key);
    if (existing) existing.rules.push(policy);
    else
      groups.set(key, {
        type: policy.subject_type,
        id: policy.subject_id,
        rules: [policy],
      });
  }

  const governedAgentIds = new Set<string>();

  const toSubject = (
    key: string,
    type: Policy["subject_type"],
    id: string,
    rules: Policy[]
  ): MatrixSubject => {
    const isWorkspace = type === "workspace";
    const enabledRules = rules.filter((r) => r.enabled);
    const { dimensions, customCount } = buildDimensions(enabledRules);
    const subjectName = isWorkspace
      ? "Workspace"
      : type === "agent"
        ? agentNameById.get(id) ?? id
        : `${type}:${id}`;

    if (type === "agent") governedAgentIds.add(id);

    return {
      subjectKey: isWorkspace ? WORKSPACE_SUBJECT_KEY : key,
      subjectType: isWorkspace ? "workspace" : "agent",
      subjectId: id,
      subjectName,
      enabled: enabledRules.length > 0,
      dimensions,
      customCount,
      rules: rules.map(policyToRule),
      hasActiveRule: enabledRules.length > 0,
    };
  };

  const subjects: MatrixSubject[] = [];
  // Workspace first.
  const workspaceGroup = groups.get(WORKSPACE_SUBJECT_KEY);
  if (workspaceGroup) {
    subjects.push(
      toSubject(
        WORKSPACE_SUBJECT_KEY,
        workspaceGroup.type,
        workspaceGroup.id,
        workspaceGroup.rules
      )
    );
  }
  for (const [key, group] of groups) {
    if (key === WORKSPACE_SUBJECT_KEY) continue;
    subjects.push(toSubject(key, group.type, group.id, group.rules));
  }

  const noBudgetCapCount = subjects.filter(
    (s) => s.dimensions.budget.value === null
  ).length;
  const noApprovalCount = subjects.filter(
    (s) => s.dimensions.approval.value === null
  ).length;
  const ungovernedAgentCount = agents.filter(
    (a) => !governedAgentIds.has(a.id)
  ).length;
  const customCount = subjects.reduce((sum, s) => sum + s.customCount, 0);

  return {
    subjects,
    governedCount: subjects.length,
    noBudgetCapCount,
    noApprovalCount,
    ungovernedAgentCount,
    customCount,
  };
}
