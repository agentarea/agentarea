"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Link as LinkIcon, Plus, UsersRound, X } from "lucide-react";
import { AgentIdentity } from "@/components/AgentIdentity";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";
import type { Policy, PolicyEffect } from "@/types/policies";
import { EFFECT_STYLES } from "./policy-effects";

// What the editor is operating on. Create modes pre-scope the rule to a
// subject (workspace, or a picked agent); edit mode locks the subject.
export type PolicyEditorTarget =
  | { mode: "create-workspace" }
  | { mode: "create-agent"; agentId?: string }
  | { mode: "edit"; policy: Policy };

interface AgentOption {
  id: string;
  name: string;
  icon?: string | null;
  color_token?: string | null;
  tools?: ToolConfigLike[] | null;
  tools_config?: ToolsConfigLike | null;
}

interface PolicyEditorProps {
  target: PolicyEditorTarget;
  agents: AgentOption[];
  workspaceId: string | null;
  returnHref?: string;
}

// Effects the editor can author. (`allow` exists in the model but tool grants
// live in the Access view; the editor focuses on restrictions.)
const EDITABLE_EFFECTS: PolicyEffect[] = ["cap", "deny", "approval", "safety"];

// --- cap sub-form ---------------------------------------------------------

type CapKind = "spend" | "service" | "tokens";
type ScopeMode = "workspace" | "agents";
type PolicyPeriod = "month" | "run";

interface ToolConfigLike {
  type?: string | null;
  name?: string | null;
  settings?: {
    allowed_tools?: unknown;
    disabled_methods?: unknown;
  } | null;
}

interface ToolsConfigLike {
  builtin_tools?: Array<{ tool_name?: string | null } | null> | null;
  mcp_server_configs?: Array<{
    allowed_tools?: unknown;
    tools?: unknown;
  } | null> | null;
  openapi_configs?: Array<{
    allowed_tools?: unknown;
  } | null> | null;
}

interface ToolOption {
  id: string;
  label: string;
  source: string;
  agents: string[];
}

interface FormState {
  enabled: boolean;
  // cap
  capKind: CapKind;
  amountUsd: string;
  period: PolicyPeriod;
  maxTokens: string;
  maxTokensPerCall: string;
  // deny / approval tools
  tools: string[];
  // approval
  approvalAllActions: boolean;
  approvers: string[];
  // safety
  promptInjection: boolean;
  outputSanitizer: boolean;
}

const EMPTY_FORM: FormState = {
  enabled: true,
  capKind: "spend",
  amountUsd: "",
  period: "month",
  maxTokens: "",
  maxTokensPerCall: "",
  tools: [],
  approvalAllActions: true,
  approvers: [],
  promptInjection: true,
  outputSanitizer: false,
};

// Loosely validate Keto subject refs (user:<id> | group:<id>#member, etc.).
const SUBJECT_REF_RE = /^[a-zA-Z]+:[^\s]+/;

function parseMoney(value: string): string | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  if (Number.isNaN(n)) return null;
  return n.toFixed(2);
}

function parseInt2(value: string): number | null {
  const trimmed = value.trim();
  if (!trimmed) return null;
  const n = Number(trimmed);
  if (Number.isNaN(n) || !Number.isInteger(n)) return null;
  return n;
}

function str(value: unknown): string {
  if (typeof value === "string") return value;
  if (typeof value === "number") return String(value);
  return "";
}

function asToolNames(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value
    .map((item) => {
      if (typeof item === "string") return item;
      if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        return str(record.tool_name) || str(record.name);
      }
      return "";
    })
    .map((item) => item.trim())
    .filter(Boolean);
}

function humanizeToolName(name: string): string {
  return name
    .replace(/^tool:/, "")
    .replace(/[_-]+/g, " ")
    .replace(/\b\w/g, (char) => char.toUpperCase());
}

function addToolOption(
  map: Map<string, ToolOption>,
  id: string,
  source: string,
  agentName: string
) {
  const normalized = id.trim();
  if (!normalized) return;
  const existing = map.get(normalized);
  if (existing) {
    if (!existing.agents.includes(agentName)) existing.agents.push(agentName);
    return;
  }
  map.set(normalized, {
    id: normalized,
    label: humanizeToolName(normalized),
    source,
    agents: [agentName],
  });
}

function buildToolCatalog(agents: AgentOption[]): ToolOption[] {
  const map = new Map<string, ToolOption>();
  for (const agent of agents) {
    const agentName = agent.name;

    for (const tool of agent.tools ?? []) {
      const name = str(tool?.name);
      if (tool?.type === "mcp" || tool?.type === "openapi") {
        const allowedTools = asToolNames(tool.settings?.allowed_tools);
        for (const allowed of allowedTools) {
          addToolOption(map, allowed, tool.type, agentName);
        }
        if (allowedTools.length === 0) {
          addToolOption(map, name, tool.type, agentName);
        }
      } else {
        addToolOption(
          map,
          name,
          tool?.type === "code" ? "builtin" : "tool",
          agentName
        );
      }
    }

    for (const builtin of agent.tools_config?.builtin_tools ?? []) {
      addToolOption(map, str(builtin?.tool_name), "builtin", agentName);
    }
    for (const mcp of agent.tools_config?.mcp_server_configs ?? []) {
      for (const name of [
        ...asToolNames(mcp?.allowed_tools),
        ...asToolNames(mcp?.tools),
      ]) {
        addToolOption(map, name, "mcp", agentName);
      }
    }
    for (const openapi of agent.tools_config?.openapi_configs ?? []) {
      for (const name of asToolNames(openapi?.allowed_tools)) {
        addToolOption(map, name, "openapi", agentName);
      }
    }
  }

  return Array.from(map.values()).sort((a, b) =>
    a.label.localeCompare(b.label)
  );
}

// Seed the form from an existing rule (edit mode). Unknown shapes degrade
// gracefully — fields that don't apply stay at their defaults.
function policyToForm(policy: Policy): {
  effect: PolicyEffect;
  form: FormState;
} {
  const p =
    typeof policy.params === "object" && policy.params !== null
      ? (policy.params as Record<string, unknown>)
      : {};
  const form: FormState = { ...EMPTY_FORM, enabled: policy.enabled };

  if (policy.effect === "cap") {
    if (policy.target === "tokens") {
      form.capKind = "tokens";
      form.maxTokens = str(p.max_tokens);
      form.maxTokensPerCall = str(p.max_tokens_per_call);
    } else if (policy.target === "service") {
      form.capKind = "service";
      form.amountUsd = str(p.amount_usd);
    } else {
      form.capKind = "spend";
      form.amountUsd = str(p.amount_usd);
      form.period = p.period === "run" ? "run" : "month";
    }
  } else if (policy.effect === "deny") {
    form.tools = policy.target.startsWith("tool:")
      ? [policy.target.slice("tool:".length)]
      : [];
  } else if (policy.effect === "approval") {
    form.approvalAllActions =
      policy.target === "*" || policy.target === "tool:*";
    form.tools =
      policy.target.startsWith("tool:") && policy.target !== "tool:*"
        ? [policy.target.slice("tool:".length)]
        : [];
    form.approvers = Array.isArray(p.approvers)
      ? (p.approvers as unknown[]).map(String).filter(Boolean)
      : [];
  } else if (policy.effect === "safety") {
    form.promptInjection = Boolean(p.prompt_injection);
    form.outputSanitizer = Boolean(p.output_sanitizer);
  }

  return { effect: policy.effect, form };
}

// A single rule body for POST /PATCH. Deny/approval over multiple tools fan out
// into several bodies (one rule per tool).
interface RuleBody {
  target: string;
  effect: PolicyEffect;
  params: Record<string, unknown>;
}

// Build the rule bodies the form describes. Returns an error string instead
// when the form is incomplete.
function buildRuleBodies(
  effect: PolicyEffect,
  form: FormState
): { bodies: RuleBody[] } | { error: string } {
  if (effect === "cap") {
    if (form.capKind === "tokens") {
      const maxTokens = parseInt2(form.maxTokens);
      const perCall = parseInt2(form.maxTokensPerCall);
      if (maxTokens === null && perCall === null)
        return { error: "Enter a token budget." };
      const params: Record<string, unknown> = {};
      if (maxTokens !== null) params.max_tokens = maxTokens;
      if (perCall !== null) params.max_tokens_per_call = perCall;
      return { bodies: [{ target: "tokens", effect, params }] };
    }
    const amount = parseMoney(form.amountUsd);
    if (amount === null) return { error: "Enter a valid amount." };
    if (form.capKind === "service")
      return {
        bodies: [{ target: "service", effect, params: { amount_usd: amount } }],
      };
    return {
      bodies: [
        {
          target: "spend",
          effect,
          params: { amount_usd: amount, period: form.period },
        },
      ],
    };
  }

  if (effect === "deny") {
    if (form.tools.length === 0) return { error: "Add at least one tool." };
    return {
      bodies: form.tools.map((tool) => ({
        target: `tool:${tool}`,
        effect,
        params: {},
      })),
    };
  }

  if (effect === "approval") {
    const params: Record<string, unknown> = {};
    if (form.approvers.length > 0) params.approvers = form.approvers;
    if (form.approvalAllActions)
      return { bodies: [{ target: "*", effect, params }] };
    if (form.tools.length === 0)
      return { error: "Add a tool or require approval for all actions." };
    return {
      bodies: form.tools.map((tool) => ({
        target: `tool:${tool}`,
        effect,
        params,
      })),
    };
  }

  // safety
  if (!form.promptInjection && !form.outputSanitizer)
    return { error: "Enable at least one safety check." };
  return {
    bodies: [
      {
        target: "content",
        effect,
        params: {
          prompt_injection: form.promptInjection,
          output_sanitizer: form.outputSanitizer,
        },
      },
    ],
  };
}

// --- small building blocks ------------------------------------------------

function EffectSegmented({
  value,
  onChange,
  disabled,
}: {
  value: PolicyEffect;
  onChange: (effect: PolicyEffect) => void;
  disabled?: boolean;
}) {
  return (
    <div className="inline-flex flex-wrap items-center gap-px border border-border/70 bg-muted/30 p-px">
      {EDITABLE_EFFECTS.map((effect) => {
        const style = EFFECT_STYLES[effect];
        const Icon = style.icon;
        const active = effect === value;
        return (
          <button
            key={effect}
            type="button"
            disabled={disabled}
            onClick={() => onChange(effect)}
            className={cn(
              "inline-flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors disabled:cursor-not-allowed disabled:opacity-60",
              active
                ? "bg-background text-foreground shadow-[inset_0_-2px_0_hsl(var(--primary))]"
                : "text-muted-foreground hover:text-foreground"
            )}
          >
            <Icon
              className="h-3.5 w-3.5 shrink-0"
              strokeWidth={1.8}
              aria-hidden
            />
            {style.label}
          </button>
        );
      })}
    </div>
  );
}

function TagInput({
  values,
  onChange,
  placeholder,
  validate,
  invalidHint,
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
  validate?: (value: string) => boolean;
  invalidHint?: string;
}) {
  const [draft, setDraft] = useState("");
  const [hint, setHint] = useState<string | null>(null);

  const add = () => {
    const value = draft.trim();
    if (!value) return;
    if (validate && !validate(value)) {
      setHint(invalidHint ?? "Invalid value");
      return;
    }
    if (!values.includes(value)) onChange([...values, value]);
    setDraft("");
    setHint(null);
  };

  return (
    <div className="space-y-1.5">
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((value) => (
            <span
              key={value}
              className="inline-flex items-center gap-1 border border-border/70 bg-muted/30 px-2 py-0.5 font-mono text-xs"
            >
              {value}
              <button
                type="button"
                aria-label={`Remove ${value}`}
                onClick={() => onChange(values.filter((v) => v !== value))}
                className="text-muted-foreground hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}
      <div className="flex gap-2">
        <Input
          value={draft}
          onChange={(e) => {
            setDraft(e.target.value);
            setHint(null);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
        />
        <Button type="button" variant="outline" size="sm" onClick={add}>
          Add
        </Button>
      </div>
      {hint && <p className="text-xs text-destructive">{hint}</p>}
    </div>
  );
}

function ToolSelector({
  options,
  values,
  onChange,
  emptyText,
}: {
  options: ToolOption[];
  values: string[];
  onChange: (next: string[]) => void;
  emptyText: string;
}) {
  const visibleOptions = useMemo(() => {
    const byId = new Map(options.map((option) => [option.id, option]));
    for (const value of values) {
      if (!byId.has(value)) {
        byId.set(value, {
          id: value,
          label: humanizeToolName(value),
          source: "custom",
          agents: [],
        });
      }
    }
    return Array.from(byId.values()).sort((a, b) =>
      a.label.localeCompare(b.label)
    );
  }, [options, values]);

  const toggle = (toolId: string) => {
    if (values.includes(toolId)) {
      onChange(values.filter((value) => value !== toolId));
    } else {
      onChange([...values, toolId]);
    }
  };

  return (
    <div className="space-y-3">
      {visibleOptions.length > 0 ? (
        <div className="grid gap-2 md:grid-cols-2">
          {visibleOptions.map((tool) => {
            const selected = values.includes(tool.id);
            const agentLabel =
              tool.agents.length > 0
                ? tool.agents.length === 1
                  ? tool.agents[0]
                  : `${tool.agents.length} agents`
                : "not in current agent catalog";
            return (
              <div
                key={tool.id}
                role="checkbox"
                tabIndex={0}
                aria-checked={selected}
                onClick={() => toggle(tool.id)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" || event.key === " ") {
                    event.preventDefault();
                    toggle(tool.id);
                  }
                }}
                className={cn(
                  "cursor-pointer",
                  "flex min-h-[58px] items-start gap-2 border border-border/70 bg-background px-3 py-2 text-left transition-colors hover:bg-muted/30",
                  selected && "shadow-[inset_2px_0_0_hsl(var(--primary))]"
                )}
              >
                <Checkbox
                  checked={selected}
                  tabIndex={-1}
                  aria-hidden="true"
                  className="pointer-events-none mt-0.5"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-medium text-foreground">
                    {tool.label}
                  </span>
                  <span className="mt-1 flex flex-wrap gap-1.5 font-mono text-[10px] uppercase tracking-[0.12em] text-muted-foreground">
                    <span>{tool.source}</span>
                    <span>{agentLabel}</span>
                  </span>
                </span>
              </div>
            );
          })}
        </div>
      ) : (
        <p className="border border-dashed border-border/70 px-3 py-3 text-sm text-muted-foreground">
          {emptyText}
        </p>
      )}

      <details className="border-t border-border/60 pt-3">
        <summary className="cursor-pointer font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
          Advanced selector
        </summary>
        <div className="mt-3">
          <TagInput
            values={values.filter(
              (value) => !options.some((option) => option.id === value)
            )}
            onChange={(customValues) => {
              const catalogValues = values.filter((value) =>
                options.some((option) => option.id === value)
              );
              onChange([...catalogValues, ...customValues]);
            }}
            placeholder="Tool name"
          />
        </div>
      </details>
    </div>
  );
}

function MoneyField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <div className="relative">
        <span className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-sm text-muted-foreground">
          $
        </span>
        <Input
          id={id}
          inputMode="decimal"
          value={value}
          onChange={(e) => onChange(e.target.value)}
          placeholder="0.00"
          className="pl-6"
        />
      </div>
    </div>
  );
}

function NumberField({
  id,
  label,
  value,
  onChange,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        inputMode="numeric"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder="optional"
      />
    </div>
  );
}

function BlueprintSection({
  code,
  title,
  children,
  className,
}: {
  code: string;
  title: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section
      className={cn(
        "grid gap-3 border-t border-border/70 py-4 md:grid-cols-[104px_minmax(0,1fr)]",
        className
      )}
    >
      <div className="flex items-start gap-2 text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
        <span className="font-mono text-foreground/70">{code}</span>
        <span>{title}</span>
      </div>
      <div className="min-w-0">{children}</div>
    </section>
  );
}

function previewTarget(effect: PolicyEffect, form: FormState): string {
  if (effect === "cap") return form.capKind;
  if (effect === "deny") {
    return form.tools.length === 0 ? "tool:<pending>" : "tool";
  }
  if (effect === "approval") {
    return form.approvalAllActions ? "*" : "tool";
  }
  return "content";
}

function previewParams(effect: PolicyEffect, form: FormState): string {
  if (effect === "cap") {
    if (form.capKind === "tokens") {
      const parts: string[] = [];
      if (form.maxTokens) parts.push(`max=${form.maxTokens}`);
      if (form.maxTokensPerCall) parts.push(`call=${form.maxTokensPerCall}`);
      return parts.length > 0 ? parts.join(" ") : "tokens=pending";
    }
    return `amount=${form.amountUsd || "pending"}${
      form.capKind === "spend" ? ` period=${form.period}` : ""
    }`;
  }
  if (effect === "deny") {
    return form.tools.length > 0
      ? `tools=${form.tools.length}`
      : "tools=pending";
  }
  if (effect === "approval") {
    const scope = form.approvalAllActions
      ? "actions=*"
      : `tools=${form.tools.length || "pending"}`;
    const approvers =
      form.approvers.length > 0 ? ` approvers=${form.approvers.length}` : "";
    return `${scope}${approvers}`;
  }
  const checks = [
    form.promptInjection && "prompt_injection",
    form.outputSanitizer && "output_sanitizer",
  ].filter(Boolean);
  return checks.length > 0 ? checks.join(" ") : "checks=pending";
}

// --- editor ---------------------------------------------------------------

export default function PolicyEditor({
  target,
  agents,
  workspaceId,
  returnHref = "/policies",
}: PolicyEditorProps) {
  const router = useRouter();
  const [effect, setEffect] = useState<PolicyEffect>("cap");
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [scopeMode, setScopeMode] = useState<ScopeMode>("workspace");
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);
  const [agentToAddId, setAgentToAddId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEdit = target?.mode === "edit";

  const subjectType = useMemo<"workspace" | "agent">(() => {
    if (target.mode === "edit")
      return target.policy.subject_type === "workspace" ? "workspace" : "agent";
    return scopeMode === "agents" ? "agent" : "workspace";
  }, [scopeMode, target]);

  const selectedAgents = useMemo(
    () =>
      selectedAgentIds
        .map((agentId) => agents.find((agent) => agent.id === agentId))
        .filter((agent): agent is AgentOption => Boolean(agent)),
    [agents, selectedAgentIds]
  );

  const selectedAgentIdSet = useMemo(
    () => new Set(selectedAgentIds),
    [selectedAgentIds]
  );

  const addableAgents = useMemo(
    () => agents.filter((agent) => !selectedAgentIdSet.has(agent.id)),
    [agents, selectedAgentIdSet]
  );

  const affectedAgents = useMemo(() => {
    if (subjectType === "workspace") return agents;
    return selectedAgents;
  }, [agents, selectedAgents, subjectType]);

  const toolCatalog = useMemo(
    () => buildToolCatalog(affectedAgents),
    [affectedAgents]
  );

  // Reset form whenever the route opens for a target.
  useEffect(() => {
    if (target.mode === "edit") {
      const seeded = policyToForm(target.policy);
      setEffect(seeded.effect);
      setForm(seeded.form);
      setScopeMode(
        target.policy.subject_type === "agent" ? "agents" : "workspace"
      );
      setSelectedAgentIds(
        target.policy.subject_type === "agent" ? [target.policy.subject_id] : []
      );
      setAgentToAddId("");
    } else {
      setEffect("cap");
      setForm(EMPTY_FORM);
      setScopeMode(target.mode === "create-agent" ? "agents" : "workspace");
      setSelectedAgentIds(
        target.mode === "create-agent" && target.agentId ? [target.agentId] : []
      );
      setAgentToAddId("");
    }
    setError(null);
  }, [target]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const addSelectedAgent = () => {
    if (!agentToAddId || selectedAgentIdSet.has(agentToAddId)) return;
    setSelectedAgentIds((prev) => [...prev, agentToAddId]);
    setAgentToAddId("");
  };

  const removeSelectedAgent = (agentId: string) => {
    setSelectedAgentIds((prev) => prev.filter((id) => id !== agentId));
    if (agentToAddId === agentId) setAgentToAddId("");
  };

  const resolveSubjects = (): Array<{
    subject_type: "workspace" | "agent";
    subject_id: string;
  }> | null => {
    if (target?.mode === "edit") {
      return [
        {
          subject_type:
            target.policy.subject_type === "workspace" ? "workspace" : "agent",
          subject_id: target.policy.subject_id,
        },
      ];
    }
    if (subjectType === "agent") {
      if (selectedAgentIds.length === 0) return null;
      return selectedAgentIds.map((agentId) => ({
        subject_type: "agent",
        subject_id: agentId,
      }));
    }
    return workspaceId
      ? [{ subject_type: "workspace", subject_id: workspaceId }]
      : null;
  };

  const save = async () => {
    const subjects = resolveSubjects();
    if (!subjects) {
      setError(
        subjectType === "agent"
          ? "Add at least one agent for this policy."
          : "No workspace context available."
      );
      return;
    }

    const built = buildRuleBodies(effect, form);
    if ("error" in built) {
      setError(built.error);
      return;
    }

    setSaving(true);
    setError(null);
    try {
      if (isEdit && target?.mode === "edit") {
        // PATCH the single rule. Edit only writes the first body (a rule edits
        // one rule); extra tools added in edit mode are ignored to keep edit
        // 1:1 with the backing rule.
        const body = built.bodies[0];
        const response = await fetch(
          `/api/proxy/v1/policies/${target.policy.id}`,
          {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({
              target: body.target,
              effect: body.effect,
              params: body.params,
              enabled: form.enabled,
            }),
          }
        );
        if (!response.ok) {
          setError(await readDetail(response, "Save failed"));
          return;
        }
      } else {
        // POST one rule per scope/body pair (deny/approval may fan out over tools).
        for (const subject of subjects) {
          for (const body of built.bodies) {
            const response = await fetch(`/api/proxy/v1/policies`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({
                subject_type: subject.subject_type,
                subject_id: subject.subject_id,
                target: body.target,
                effect: body.effect,
                params: body.params,
                enabled: form.enabled,
              }),
            });
            if (!response.ok) {
              setError(await readDetail(response, "Save failed"));
              return;
            }
          }
        }
      }

      router.push(returnHref);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save policy");
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (target?.mode !== "edit") return;
    setSaving(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/proxy/v1/policies/${target.policy.id}`,
        {
          method: "DELETE",
        }
      );
      if (!response.ok && response.status !== 204) {
        setError(await readDetail(response, "Delete failed"));
        return;
      }
      router.push(returnHref);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to delete policy");
    } finally {
      setSaving(false);
    }
  };

  const title = isEdit
    ? "Edit policy rule"
    : subjectType === "agent"
      ? "New agent policy"
      : "New workspace rule";
  const hasAgentScopeEditor = subjectType === "agent" && !isEdit;
  const effectCode = hasAgentScopeEditor ? "03" : "02";
  const detailsCode = hasAgentScopeEditor ? "04" : "03";
  const stateCode = hasAgentScopeEditor ? "05" : "04";
  const compiledSubjects = resolveSubjects();
  const compiledBodies = buildRuleBodies(effect, form);
  const compiledError =
    compiledSubjects === null
      ? subjectType === "agent"
        ? "agent scope pending"
        : "workspace scope missing"
      : "error" in compiledBodies
        ? compiledBodies.error
        : null;
  const compiledRuleCount =
    compiledSubjects && "bodies" in compiledBodies
      ? compiledSubjects.length * compiledBodies.bodies.length
      : null;
  const compiledRows = [
    {
      label: "scope",
      value:
        subjectType === "workspace"
          ? "workspace"
          : `${selectedAgentIds.length} agent${selectedAgentIds.length === 1 ? "" : "s"}`,
    },
    { label: "effect", value: EFFECT_STYLES[effect].label.toLowerCase() },
    { label: "target", value: previewTarget(effect, form) },
    { label: "params", value: previewParams(effect, form) },
    {
      label: "rules",
      value: compiledRuleCount === null ? "pending" : String(compiledRuleCount),
    },
    { label: "state", value: form.enabled ? "enabled" : "disabled" },
  ];

  return (
    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_300px]">
      <section className="relative overflow-hidden border border-border/70 bg-background">
        <div
          className="pointer-events-none absolute inset-0 opacity-[0.025]"
          style={{
            backgroundImage:
              "linear-gradient(to right, currentColor 1px, transparent 1px), linear-gradient(to bottom, currentColor 1px, transparent 1px)",
            backgroundSize: "18px 18px",
          }}
          aria-hidden="true"
        />
        <div className="relative border-b border-border/70 bg-muted/20 px-5 py-4">
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-0 space-y-1">
              <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Policy Control Plane
              </p>
              <h2 className="text-lg font-semibold text-foreground">{title}</h2>
              <p className="max-w-2xl text-sm text-muted-foreground">
                This policy applies to{" "}
                {subjectType === "workspace"
                  ? "every agent in this workspace"
                  : selectedAgents.length === 1
                    ? "the selected agent"
                    : "the selected agents"}
                . Tool access grants are managed in the Access view.
              </p>
            </div>
            <div className="border border-border/70 bg-background px-3 py-2 text-right">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                Scope
              </p>
              <p className="mt-1 text-sm font-medium text-foreground">
                {subjectType === "workspace" ? "All agents" : "Selected"}
              </p>
            </div>
          </div>
        </div>

        <div className="relative px-5">
          {!isEdit && (
            <BlueprintSection code="01" title="Scope">
              <div className="inline-flex flex-wrap items-center gap-px border border-border/70 bg-muted/30 p-px">
                {[
                  { value: "workspace" as const, label: "All agents" },
                  { value: "agents" as const, label: "Selected agents" },
                ].map((option) => {
                  const active = scopeMode === option.value;
                  return (
                    <button
                      key={option.value}
                      type="button"
                      onClick={() => setScopeMode(option.value)}
                      className={cn(
                        "px-3 py-1.5 text-sm transition",
                        active
                          ? "bg-background text-foreground shadow-[inset_0_-2px_0_hsl(var(--primary))]"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      {option.label}
                    </button>
                  );
                })}
              </div>
            </BlueprintSection>
          )}

          {isEdit && (
            <BlueprintSection code="01" title="Scope">
              <p className="mt-1 text-sm text-foreground">
                {subjectType === "workspace"
                  ? "All agents"
                  : selectedAgents[0]?.name || target.policy.subject_id}
              </p>
            </BlueprintSection>
          )}

          {hasAgentScopeEditor && (
            <BlueprintSection code="02" title="Agents">
              <div className="space-y-3">
                <div className="flex items-end gap-2">
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <Label htmlFor="policy-agent">Agent</Label>
                    <Select
                      value={agentToAddId}
                      onValueChange={setAgentToAddId}
                    >
                      <SelectTrigger id="policy-agent">
                        <SelectValue placeholder="Select an agent" />
                      </SelectTrigger>
                      <SelectContent>
                        {addableAgents.map((agent) => (
                          <SelectItem
                            key={agent.id}
                            value={agent.id}
                            textValue={agent.name}
                          >
                            <AgentIdentity agent={agent} size="xs" />
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="icon"
                    disabled={!agentToAddId}
                    onClick={addSelectedAgent}
                    aria-label="Add agent"
                  >
                    <Plus className="h-4 w-4" />
                  </Button>
                </div>

                <div className="space-y-2">
                  {selectedAgents.length > 0 ? (
                    selectedAgents.map((agent) => (
                      <div
                        key={agent.id}
                        className="flex items-center gap-2 border border-border/70 bg-muted/20 px-3 py-2"
                      >
                        <AgentIdentity
                          agent={agent}
                          size="xs"
                          className="flex-1"
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          onClick={() => removeSelectedAgent(agent.id)}
                          aria-label={`Remove ${agent.name}`}
                        >
                          <X className="h-4 w-4" />
                        </Button>
                      </div>
                    ))
                  ) : (
                    <p className="border border-dashed border-border/70 px-3 py-3 text-sm text-muted-foreground">
                      Add agents to scope this policy.
                    </p>
                  )}
                </div>
              </div>
            </BlueprintSection>
          )}

          {/* Effect */}
          <BlueprintSection code={effectCode} title="Effect">
            <EffectSegmented
              value={effect}
              onChange={setEffect}
              disabled={isEdit}
            />
            {isEdit && (
              <p className="text-xs text-muted-foreground">
                The effect is fixed once a rule is created.
              </p>
            )}
          </BlueprintSection>

          {/* Effect-specific fields */}
          {effect === "cap" && (
            <BlueprintSection code={detailsCode} title="Limits">
              <div className="space-y-3 border border-border/70 bg-muted/20 p-4">
                <div className="space-y-1.5">
                  <Label htmlFor="cap-kind">Budget type</Label>
                  <Select
                    value={form.capKind}
                    onValueChange={(v) => update("capKind", v as CapKind)}
                  >
                    <SelectTrigger id="cap-kind">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="spend">Spend budget</SelectItem>
                      <SelectItem value="service">
                        Per-service budget
                      </SelectItem>
                      <SelectItem value="tokens">Token budget</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {form.capKind === "tokens" ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <NumberField
                      id="max-tokens"
                      label="Max tokens"
                      value={form.maxTokens}
                      onChange={(v) => update("maxTokens", v)}
                    />
                    <NumberField
                      id="max-tokens-call"
                      label="Max tokens per call"
                      value={form.maxTokensPerCall}
                      onChange={(v) => update("maxTokensPerCall", v)}
                    />
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <MoneyField
                      id="cap-amount"
                      label="Amount"
                      value={form.amountUsd}
                      onChange={(v) => update("amountUsd", v)}
                    />
                    {form.capKind === "spend" && (
                      <div className="space-y-1.5">
                        <Label htmlFor="cap-period">Period</Label>
                        <Select
                          value={form.period}
                          onValueChange={(v) =>
                            update("period", v as PolicyPeriod)
                          }
                        >
                          <SelectTrigger id="cap-period">
                            <SelectValue />
                          </SelectTrigger>
                          <SelectContent>
                            <SelectItem value="month">Per month</SelectItem>
                            <SelectItem value="run">Per task</SelectItem>
                          </SelectContent>
                        </Select>
                      </div>
                    )}
                  </div>
                )}
              </div>
            </BlueprintSection>
          )}

          {effect === "deny" && (
            <BlueprintSection code={detailsCode} title="Deny List">
              <div className="space-y-3 border border-border/70 bg-muted/20 p-4">
                <Label>Denied tools</Label>
                <ToolSelector
                  options={toolCatalog}
                  values={form.tools}
                  onChange={(next) => update("tools", next)}
                  emptyText="No tools are attached to the affected agents yet."
                />
                <p className="flex items-center gap-1 text-xs text-muted-foreground">
                  <LinkIcon className="h-3 w-3" />
                  Granting tool access is managed in the{" "}
                  <Link
                    href="/policies?view=access"
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    Access view
                  </Link>
                  .
                </p>
              </div>
            </BlueprintSection>
          )}

          {effect === "approval" && (
            <BlueprintSection code={detailsCode} title="Approval">
              <div className="space-y-3 border border-border/70 bg-muted/20 p-4">
                <div className="flex items-center justify-between">
                  <div>
                    <Label htmlFor="approval-all">
                      Require for all actions
                    </Label>
                    <p className="text-xs text-muted-foreground">
                      Off to require approval for specific tools only.
                    </p>
                  </div>
                  <Switch
                    id="approval-all"
                    checked={form.approvalAllActions}
                    onCheckedChange={(v) => update("approvalAllActions", v)}
                  />
                </div>
                {!form.approvalAllActions && (
                  <div className="space-y-1.5">
                    <Label>Tools requiring approval</Label>
                    <ToolSelector
                      options={toolCatalog}
                      values={form.tools}
                      onChange={(next) => update("tools", next)}
                      emptyText="No tools are attached to the affected agents yet."
                    />
                  </div>
                )}
                <div className="space-y-1.5">
                  <Label>Approvers</Label>
                  <TagInput
                    values={form.approvers}
                    onChange={(next) => update("approvers", next)}
                    placeholder="user:<id> or group:<id>#member"
                    validate={(v) => SUBJECT_REF_RE.test(v)}
                    invalidHint="Use a subject ref like user:<id> or group:<id>#member"
                  />
                  <p className="text-xs text-muted-foreground">
                    Leave empty to allow any workspace member to approve.
                  </p>
                </div>
              </div>
            </BlueprintSection>
          )}

          {effect === "safety" && (
            <BlueprintSection code={detailsCode} title="Safety">
              <div className="space-y-3 border border-border/70 bg-muted/20 p-4">
                <div className="flex items-center justify-between">
                  <Label htmlFor="prompt-injection" className="font-normal">
                    Prompt-injection detection
                  </Label>
                  <Switch
                    id="prompt-injection"
                    checked={form.promptInjection}
                    onCheckedChange={(v) => update("promptInjection", v)}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="output-sanitizer" className="font-normal">
                    Output sanitizer
                  </Label>
                  <Switch
                    id="output-sanitizer"
                    checked={form.outputSanitizer}
                    onCheckedChange={(v) => update("outputSanitizer", v)}
                  />
                </div>
              </div>
            </BlueprintSection>
          )}

          {/* Enabled */}
          <BlueprintSection code={stateCode} title="State">
            <div className="flex items-center justify-between border border-border/70 bg-muted/20 p-4">
              <div>
                <Label htmlFor="policy-enabled">Rule enabled</Label>
                <p className="text-xs text-muted-foreground">
                  Disabled rules are kept but not enforced.
                </p>
              </div>
              <Switch
                id="policy-enabled"
                checked={form.enabled}
                onCheckedChange={(v) => update("enabled", v)}
              />
            </div>
          </BlueprintSection>
        </div>

        {error && (
          <p
            className="relative mx-5 border-t border-destructive/30 py-3 text-sm text-destructive"
            role="alert"
          >
            {error}
          </p>
        )}

        <div className="relative flex items-center justify-between gap-2 border-t border-border/70 bg-muted/20 px-5 py-4">
          {isEdit ? (
            <Button
              type="button"
              variant="destructiveOutline"
              size="sm"
              disabled={saving}
              onClick={remove}
            >
              Delete
            </Button>
          ) : (
            <span />
          )}
          <div className="flex gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={saving}
              onClick={() => router.push(returnHref)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              isLoading={saving}
              disabled={saving}
              onClick={save}
            >
              {isEdit ? "Save rule" : "Create rule"}
            </Button>
          </div>
        </div>
      </section>

      <aside className="h-fit border border-border/70 bg-background">
        <div className="border-b border-border/70 bg-muted/20 px-4 py-3">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            Impact Rail
          </p>
        </div>
        <div className="flex items-center gap-2 border-b border-border/70 px-4 py-3">
          <span className="grid h-8 w-8 place-items-center border border-border/70 bg-muted/40">
            <UsersRound className="h-4 w-4 text-muted-foreground" />
          </span>
          <div>
            <h3 className="text-sm font-medium text-foreground">
              Affected agents
            </h3>
            <p className="text-xs text-muted-foreground">
              {subjectType === "workspace"
                ? `${affectedAgents.length} workspace agent${affectedAgents.length === 1 ? "" : "s"}`
                : affectedAgents.length > 0
                  ? `${affectedAgents.length} selected agent${affectedAgents.length === 1 ? "" : "s"}`
                  : "No agents selected"}
            </p>
          </div>
        </div>

        <div className="space-y-2 p-4">
          {affectedAgents.length > 0 ? (
            affectedAgents.slice(0, 8).map((agent) => (
              <div
                key={agent.id}
                className="border border-border/70 bg-muted/20 px-3 py-2"
              >
                <AgentIdentity
                  agent={agent}
                  size="xs"
                  right={
                    <span className="text-[11px] text-muted-foreground">
                      Agent
                    </span>
                  }
                />
              </div>
            ))
          ) : (
            <p className="border border-dashed border-border/70 px-3 py-3 text-sm text-muted-foreground">
              {subjectType === "workspace"
                ? "No agents in this workspace yet."
                : "Select an agent to preview the affected scope."}
            </p>
          )}
          {affectedAgents.length > 8 && (
            <p className="text-xs text-muted-foreground">
              +{affectedAgents.length - 8} more
            </p>
          )}
        </div>

        <div className="border-t border-border/70 p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              Compiled output
            </p>
            {compiledError && (
              <span className="border border-dashed border-border/70 px-1.5 py-0.5 font-mono text-[10px] uppercase text-muted-foreground">
                pending
              </span>
            )}
          </div>
          <dl className="border border-border/70 bg-muted/20 font-mono text-[11px]">
            {compiledRows.map((row) => (
              <div
                key={row.label}
                className="grid grid-cols-[72px_minmax(0,1fr)] border-b border-border/60 last:border-b-0"
              >
                <dt className="border-r border-border/60 px-2 py-1.5 uppercase tracking-[0.12em] text-muted-foreground">
                  {row.label}
                </dt>
                <dd className="truncate px-2 py-1.5 text-foreground/85">
                  {row.value}
                </dd>
              </div>
            ))}
          </dl>
          {compiledError && (
            <p className="mt-2 text-xs text-muted-foreground">
              {compiledError}
            </p>
          )}
        </div>
      </aside>
    </div>
  );
}

// Read a backend 4xx detail message, falling back to a status-based message.
async function readDetail(
  response: Response,
  fallback: string
): Promise<string> {
  let detail = `${fallback} (${response.status})`;
  try {
    const body = (await response.json()) as { detail?: unknown };
    if (typeof body.detail === "string") {
      detail = body.detail;
    } else if (Array.isArray(body.detail)) {
      detail = body.detail
        .map((item) =>
          item && typeof item === "object" && "msg" in item
            ? String((item as { msg: unknown }).msg)
            : String(item)
        )
        .join(", ");
    }
  } catch {
    // keep the status-based message
  }
  return detail;
}
