"use client";

import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Link as LinkIcon, Plus, UsersRound, X } from "lucide-react";
import { AgentIdentity } from "@/components/AgentIdentity";
import { AgentSelect } from "@/components/AgentSelect";
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
import Link from "@/components/WorkspaceLink";
import { useCurrency } from "@/hooks/useCurrency";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import {
  resolveMcpRef,
  type McpInstance,
  type McpServer,
} from "@/lib/mcp/resolveMcpRef";
import {
  getCurrencySymbol,
  isNegativeMoneyInput,
  isPositiveMoneyInput,
  parseMoneyInput,
} from "@/lib/money";
import { cn } from "@/lib/utils";
import type { Policy, PolicyEffect } from "@/types/policies";
import {
  createPolicyRuleAction,
  deletePolicyRuleAction,
  updatePolicyRuleAction,
} from "./actions";
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

  tools?: ToolConfigLike[] | null;
  tools_config?: ToolsConfigLike | null;
}

interface PolicyEditorProps {
  target: PolicyEditorTarget;
  agents: AgentOption[];
  mcpInstances: McpInstance[];
  mcpServers: McpServer[];
  openapiConnections: OpenAPIConnectionOption[];
  members: MemberOption[];
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

interface OpenAPIConnectionOption {
  id: string;
  name: string;
  available_tools?: Array<{
    name: string;
    description?: string | null;
    inputSchema?: unknown;
  }> | null;
}

interface MemberOption {
  user_id: string;
  email?: string | null;
  display_name?: string | null;
}

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

type ToolSource = "builtin" | "custom" | "mcp" | "openapi" | "tool";

interface ToolOption {
  id: string;
  label: string;
  source: ToolSource;
  sourceName?: string;
  description?: string;
  parameterKeys: string[];
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
  approvers: string[];
  // safety
  promptInjection: boolean;
  outputSanitizer: boolean;
}

interface PolicyDraft {
  id: string;
  effect: PolicyEffect;
  form: FormState;
}

const EMPTY_FORM: FormState = {
  enabled: true,
  capKind: "spend",
  amountUsd: "",
  period: "month",
  maxTokens: "",
  maxTokensPerCall: "",
  tools: [],
  approvers: [],
  promptInjection: true,
  outputSanitizer: false,
};

function cloneForm(form: FormState): FormState {
  return {
    ...form,
    tools: [...form.tools],
    approvers: [...form.approvers],
  };
}

function newDraft(id: string, effect: PolicyEffect = "cap"): PolicyDraft {
  return {
    id,
    effect,
    form: cloneForm(EMPTY_FORM),
  };
}

// Approvers the engine resolves: only a direct workspace user ("user:<id>")
// ever grants approval, so the backend rejects role/group/userset refs (#198).
const USER_APPROVER_RE = /^user:[^\s#]+$/;

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

function schemaParameterKeys(schema: unknown): string[] {
  if (!schema || typeof schema !== "object") return [];
  const record = schema as Record<string, unknown>;
  const properties =
    record.properties && typeof record.properties === "object"
      ? (record.properties as Record<string, unknown>)
      : null;
  return properties ? Object.keys(properties).sort() : [];
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

function memberLabel(member: MemberOption): string {
  return member.display_name || member.email || member.user_id;
}

function approverLabel(ref: string, members: MemberOption[]): string {
  if (!ref.startsWith("user:")) return ref;
  const userId = ref.slice("user:".length);
  const member = members.find((item) => item.user_id === userId);
  return member ? memberLabel(member) : ref;
}

function addToolOption(
  map: Map<string, ToolOption>,
  id: string,
  source: ToolSource,
  agentName: string,
  metadata?: {
    sourceName?: string;
    description?: string | null;
    parameterKeys?: string[];
  }
) {
  const normalized = id.trim();
  if (!normalized) return;
  const existing = map.get(normalized);
  if (existing) {
    if (!existing.agents.includes(agentName)) existing.agents.push(agentName);
    if (!existing.description && metadata?.description) {
      existing.description = metadata.description;
    }
    if (metadata?.parameterKeys) {
      existing.parameterKeys = Array.from(
        new Set([...existing.parameterKeys, ...metadata.parameterKeys])
      ).sort();
    }
    return;
  }
  map.set(normalized, {
    id: normalized,
    label: humanizeToolName(normalized),
    source,
    sourceName: metadata?.sourceName,
    description: metadata?.description ?? undefined,
    parameterKeys: metadata?.parameterKeys ?? [],
    agents: [agentName],
  });
}

function buildToolCatalog(
  agents: AgentOption[],
  mcpInstances: McpInstance[],
  mcpServers: McpServer[],
  openapiConnections: OpenAPIConnectionOption[]
): ToolOption[] {
  const map = new Map<string, ToolOption>();
  const openapiById = new Map(
    openapiConnections.map((connection) => [connection.id, connection])
  );

  for (const agent of agents) {
    const agentName = agent.name;

    for (const tool of agent.tools ?? []) {
      const name = str(tool?.name);
      if (tool?.type === "mcp") {
        const ref = resolveMcpRef(name, mcpInstances, mcpServers);
        const unrestricted = tool.settings?.allowed_tools == null;
        const allowedTools = asToolNames(tool.settings?.allowed_tools);
        if (ref.status === "instance" && ref.availableTools.length > 0) {
          const allowedSet = unrestricted ? null : new Set(allowedTools);
          for (const available of ref.availableTools) {
            if (allowedSet && !allowedSet.has(available.name)) continue;
            addToolOption(map, available.name, "mcp", agentName, {
              sourceName: ref.displayName,
              description: available.description,
              parameterKeys: schemaParameterKeys(available.inputSchema),
            });
          }
        } else {
          for (const allowed of allowedTools) {
            addToolOption(map, allowed, "mcp", agentName, {
              sourceName: ref.displayName,
            });
          }
          if (unrestricted) {
            addToolOption(map, name, "mcp", agentName, {
              sourceName: ref.displayName,
            });
          }
        }
      } else if (tool?.type === "openapi") {
        const connection = openapiById.get(name);
        const unrestricted = tool.settings?.allowed_tools == null;
        const allowedTools = asToolNames(tool.settings?.allowed_tools);
        if (connection?.available_tools?.length) {
          const allowedSet = unrestricted ? null : new Set(allowedTools);
          for (const available of connection.available_tools) {
            if (allowedSet && !allowedSet.has(available.name)) continue;
            addToolOption(map, available.name, "openapi", agentName, {
              sourceName: connection.name,
              description: available.description,
              parameterKeys: schemaParameterKeys(available.inputSchema),
            });
          }
        } else {
          for (const allowed of allowedTools) {
            addToolOption(map, allowed, "openapi", agentName, {
              sourceName: connection?.name,
            });
          }
          if (unrestricted) {
            addToolOption(map, name, "openapi", agentName, {
              sourceName: connection?.name,
            });
          }
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
type RuleBuildError =
  | "tokenBudgetRequired"
  | "amountInvalid"
  | "amountMustBePositive"
  | "amountMustNotBeNegative"
  | "atLeastOneToolRequired"
  | "toolRequired"
  | "safetyCheckRequired"
  | "approverUnsupported";

// Build the rule bodies the form describes. Returns an error code instead
// when the form is incomplete.
function buildRuleBodies(
  effect: PolicyEffect,
  form: FormState
): { bodies: RuleBody[] } | { error: RuleBuildError } {
  if (effect === "cap") {
    if (form.capKind === "tokens") {
      const maxTokens = parseInt2(form.maxTokens);
      const perCall = parseInt2(form.maxTokensPerCall);
      if (maxTokens === null && perCall === null)
        return { error: "tokenBudgetRequired" };
      const params: Record<string, unknown> = {};
      if (maxTokens !== null) params.max_tokens = maxTokens;
      if (perCall !== null) params.max_tokens_per_call = perCall;
      return { bodies: [{ target: "tokens", effect, params }] };
    }
    const amount = parseMoneyInput(form.amountUsd);
    if (amount === null) return { error: "amountInvalid" };
    // A $0 monthly cap is valid (it freezes spend); per-run and service caps
    // must allow something, matching the governance rule schema.
    const zeroAllowed = form.capKind === "spend" && form.period !== "run";
    if (zeroAllowed && isNegativeMoneyInput(amount))
      return { error: "amountMustNotBeNegative" };
    if (!zeroAllowed && !isPositiveMoneyInput(amount))
      return { error: "amountMustBePositive" };
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
    if (form.tools.length === 0) return { error: "atLeastOneToolRequired" };
    return {
      bodies: form.tools.map((tool) => ({
        target: `tool:${tool}`,
        effect,
        params: {},
      })),
    };
  }

  if (effect === "approval") {
    if (form.tools.length === 0) return { error: "toolRequired" };
    if (form.approvers.some((ref) => !USER_APPROVER_RE.test(ref)))
      return { error: "approverUnsupported" };
    const params: Record<string, unknown> = {};
    if (form.approvers.length > 0) params.approvers = form.approvers;
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
    return { error: "safetyCheckRequired" };
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
  const t = useTranslations("PoliciesPage.editor");
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
            {effect === "cap"
              ? t("effects.cap")
              : effect === "deny"
                ? t("effects.deny")
                : effect === "approval"
                  ? t("effects.approval")
                  : t("effects.safety")}
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
}: {
  values: string[];
  onChange: (next: string[]) => void;
  placeholder: string;
}) {
  const t = useTranslations("PoliciesPage.editor");
  const [draft, setDraft] = useState("");

  const add = () => {
    const value = draft.trim();
    if (!value) return;
    if (!values.includes(value)) onChange([...values, value]);
    setDraft("");
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
                aria-label={t("tagInput.removeValue", { value })}
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
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") {
              e.preventDefault();
              add();
            }
          }}
          placeholder={placeholder}
        />
        <Button type="button" variant="outline" size="sm" onClick={add}>
          {t("tagInput.add")}
        </Button>
      </div>
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
  const t = useTranslations("PoliciesPage.editor");
  const visibleOptions = useMemo(() => {
    const byId = new Map(options.map((option) => [option.id, option]));
    for (const value of values) {
      if (!byId.has(value)) {
        byId.set(value, {
          id: value,
          label: humanizeToolName(value),
          source: "custom",
          parameterKeys: [],
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
                  : t("tools.agentCount", { count: tool.agents.length })
                : t("tools.notInAgentCatalog");
            const sourceLabel =
              tool.source === "mcp"
                ? tool.sourceName
                  ? t("tools.mcpSourceNamed", { name: tool.sourceName })
                  : t("tools.mcpSource")
                : tool.source === "openapi"
                  ? tool.sourceName
                    ? t("tools.openApiSourceNamed", {
                        name: tool.sourceName,
                      })
                    : t("tools.openApiSource")
                  : tool.source === "builtin"
                    ? t("tools.builtInSource")
                    : tool.source === "custom"
                      ? t("tools.customSource")
                      : t("tools.genericSource");
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
                    <span>{sourceLabel}</span>
                    <span>{agentLabel}</span>
                  </span>
                  {tool.description && (
                    <span className="mt-1 line-clamp-2 block text-xs text-muted-foreground">
                      {tool.description}
                    </span>
                  )}
                  {tool.parameterKeys.length > 0 && (
                    <span className="mt-2 flex flex-wrap gap-1">
                      {tool.parameterKeys.slice(0, 4).map((param) => (
                        <span
                          key={param}
                          className="border border-border/60 px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground"
                        >
                          {param}
                        </span>
                      ))}
                      {tool.parameterKeys.length > 4 && (
                        <span className="px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                          +{tool.parameterKeys.length - 4}
                        </span>
                      )}
                    </span>
                  )}
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
          {t("tools.advancedSelector")}
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
            placeholder={t("tools.namePlaceholder")}
          />
        </div>
      </details>
    </div>
  );
}

function ApproverSelector({
  members,
  values,
  onChange,
}: {
  members: MemberOption[];
  values: string[];
  onChange: (next: string[]) => void;
}) {
  const t = useTranslations("PoliciesPage.editor");

  const toggle = (ref: string) => {
    if (values.includes(ref)) {
      onChange(values.filter((value) => value !== ref));
    } else {
      onChange([...values, ref]);
    }
  };

  const unsupportedCount = values.filter(
    (ref) => !USER_APPROVER_RE.test(ref)
  ).length;

  return (
    <div className="space-y-3">
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((ref) => {
            const unsupported = !USER_APPROVER_RE.test(ref);
            return (
              <span
                key={ref}
                className={cn(
                  "inline-flex items-center gap-1 border px-2 py-0.5 text-xs",
                  unsupported
                    ? "border-destructive/50 bg-destructive/10 text-destructive"
                    : "border-border/70 bg-muted/30"
                )}
              >
                {approverLabel(ref, members)}
                <button
                  type="button"
                  aria-label={t("tagInput.removeValue", { value: ref })}
                  onClick={() =>
                    onChange(values.filter((value) => value !== ref))
                  }
                  className="text-muted-foreground hover:text-foreground"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            );
          })}
        </div>
      )}
      {unsupportedCount > 0 && (
        <p className="text-xs text-destructive">
          {t("approvers.unsupportedHint", { count: unsupportedCount })}
        </p>
      )}

      <div className="grid gap-2 md:grid-cols-2">
        {members.map((member) => {
          const ref = `user:${member.user_id}`;
          const selected = values.includes(ref);
          const label = memberLabel(member);
          return (
            <div
              key={member.user_id}
              role="checkbox"
              tabIndex={0}
              aria-checked={selected}
              onClick={() => toggle(ref)}
              onKeyDown={(event) => {
                if (event.key === "Enter" || event.key === " ") {
                  event.preventDefault();
                  toggle(ref);
                }
              }}
              className={cn(
                "flex min-h-[58px] cursor-pointer items-start gap-2 border border-border/70 bg-background px-3 py-2 text-left transition-colors hover:bg-muted/30",
                selected && "shadow-[inset_2px_0_0_hsl(var(--primary))]"
              )}
            >
              <Checkbox
                checked={selected}
                tabIndex={-1}
                aria-hidden="true"
                className="pointer-events-none mt-0.5"
              />
              <span className="min-w-0">
                <span className="block truncate text-sm font-medium text-foreground">
                  {label}
                </span>
                <span className="mt-1 block truncate text-xs text-muted-foreground">
                  {member.email && member.email !== label
                    ? member.email
                    : member.user_id}
                </span>
              </span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function MoneyField({
  id,
  label,
  value,
  onChange,
  currencySymbol,
}: {
  id: string;
  label: string;
  value: string;
  onChange: (value: string) => void;
  // Required, not defaulted to "$" — the caller must pass whatever
  // getCurrencySymbol() resolved (including "¤" while the workspace's
  // currency is loading/unavailable), never a guessed symbol.
  currencySymbol: string;
}) {
  const t = useTranslations("PoliciesPage.editor");
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        inputMode="decimal"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t("budget.moneyPlaceholder")}
        leading={currencySymbol}
      />
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
  const t = useTranslations("PoliciesPage.editor");
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      <Input
        id={id}
        inputMode="numeric"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={t("budget.numberPlaceholder")}
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
    return form.tools.length === 0 ? "tool:<pending>" : "tool";
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
    const scope = `tools=${form.tools.length || "pending"}`;
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
  mcpInstances,
  mcpServers,
  openapiConnections,
  members,
  workspaceId,
  returnHref = "/policies",
}: PolicyEditorProps) {
  const router = useWorkspaceRouter();
  const locale = useLocale();
  const { currency } = useCurrency();
  const t = useTranslations("PoliciesPage.editor");
  const effectLabel = (effect: PolicyEffect) =>
    effect === "allow"
      ? t("effects.allow")
      : effect === "cap"
        ? t("effects.cap")
        : effect === "approval"
          ? t("effects.approval")
          : effect === "deny"
            ? t("effects.deny")
            : t("effects.safety");
  const ruleErrorLabel = (error: RuleBuildError) =>
    error === "tokenBudgetRequired"
      ? t("validation.tokenBudgetRequired")
      : error === "amountInvalid"
        ? t("validation.amountInvalid")
        : error === "amountMustBePositive"
          ? t("validation.amountMustBePositive")
          : error === "amountMustNotBeNegative"
            ? t("validation.amountMustNotBeNegative")
          : error === "atLeastOneToolRequired"
            ? t("validation.atLeastOneToolRequired")
            : error === "toolRequired"
              ? t("validation.toolRequired")
              : error === "approverUnsupported"
                ? t("validation.approverUnsupported")
                : t("validation.safetyCheckRequired");
  const currencySymbol = useMemo(
    () => getCurrencySymbol(currency, locale),
    [currency, locale]
  );
  const [drafts, setDrafts] = useState<PolicyDraft[]>(() => [
    newDraft("draft-1"),
  ]);
  const [activeDraftId, setActiveDraftId] = useState("draft-1");
  const [scopeMode, setScopeMode] = useState<ScopeMode>("workspace");
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);
  const [agentToAddId, setAgentToAddId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEdit = target?.mode === "edit";
  const activeDraft =
    drafts.find((draft) => draft.id === activeDraftId) ?? drafts[0];
  const effect = activeDraft?.effect ?? "cap";
  const form = activeDraft?.form ?? EMPTY_FORM;

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
    () =>
      buildToolCatalog(
        affectedAgents,
        mcpInstances,
        mcpServers,
        openapiConnections
      ),
    [affectedAgents, mcpInstances, mcpServers, openapiConnections]
  );

  // Reset form whenever the route opens for a target.
  useEffect(() => {
    if (target.mode === "edit") {
      const seeded = policyToForm(target.policy);
      setDrafts([
        {
          id: "draft-1",
          effect: seeded.effect,
          form: cloneForm(seeded.form),
        },
      ]);
      setActiveDraftId("draft-1");
      setScopeMode(
        target.policy.subject_type === "agent" ? "agents" : "workspace"
      );
      setSelectedAgentIds(
        target.policy.subject_type === "agent" ? [target.policy.subject_id] : []
      );
      setAgentToAddId("");
    } else {
      setDrafts([newDraft("draft-1")]);
      setActiveDraftId("draft-1");
      setScopeMode(target.mode === "create-agent" ? "agents" : "workspace");
      setSelectedAgentIds(
        target.mode === "create-agent" && target.agentId ? [target.agentId] : []
      );
      setAgentToAddId("");
    }
    setError(null);
  }, [target]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setDrafts((prev) =>
      prev.map((draft) =>
        draft.id === activeDraftId
          ? { ...draft, form: { ...draft.form, [key]: value } }
          : draft
      )
    );

  const updateActiveEffect = (nextEffect: PolicyEffect) => {
    setDrafts((prev) =>
      prev.map((draft) =>
        draft.id === activeDraftId ? { ...draft, effect: nextEffect } : draft
      )
    );
  };

  const addDraft = () => {
    const id = `draft-${drafts.length + 1}-${Date.now()}`;
    setDrafts((prev) => [...prev, newDraft(id, "deny")]);
    setActiveDraftId(id);
  };

  const removeDraft = (draftId: string) => {
    if (drafts.length <= 1) return;
    const nextActiveId =
      activeDraftId === draftId
        ? (drafts.find((draft) => draft.id !== draftId)?.id ?? "draft-1")
        : activeDraftId;
    setDrafts((prev) => prev.filter((draft) => draft.id !== draftId));
    setActiveDraftId(nextActiveId);
  };

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
          ? t("validation.agentRequired")
          : t("validation.workspaceRequired")
      );
      return;
    }

    const draftsToSave = isEdit ? [activeDraft] : drafts;
    const builtDrafts = draftsToSave.map((draft, index) => ({
      draft,
      index,
      result: buildRuleBodies(draft.effect, draft.form),
    }));
    const invalidDraft = builtDrafts.find((item) => "error" in item.result);
    if (invalidDraft && "error" in invalidDraft.result) {
      setActiveDraftId(invalidDraft.draft.id);
      setError(
        t("validation.ruleInvalid", {
          number: invalidDraft.index + 1,
          effect: effectLabel(invalidDraft.draft.effect),
          error: ruleErrorLabel(invalidDraft.result.error),
        })
      );
      return;
    }

    setSaving(true);
    setError(null);
    try {
      if (isEdit && target?.mode === "edit") {
        // PATCH the single rule. Edit only writes the first body (a rule edits
        // one rule); extra tools added in edit mode are ignored to keep edit
        // 1:1 with the backing rule.
        const built = builtDrafts[0].result;
        if ("error" in built) return;
        const body = built.bodies[0];
        const result = await updatePolicyRuleAction(target.policy.id, {
          target: body.target,
          effect: body.effect,
          params: body.params,
          // Conditions are not evaluated (the compiler applies the rule to
          // every call), so an edit clears any stored one to match runtime.
          condition: null,
          enabled: activeDraft.form.enabled,
        });
        if (!result.ok) {
          setError(result.error);
          return;
        }
      } else {
        // POST one rule per scope/body pair (deny/approval may fan out over tools).
        for (const subject of subjects) {
          for (const item of builtDrafts) {
            if ("error" in item.result) continue;
            for (const body of item.result.bodies) {
              try {
                const result = await createPolicyRuleAction({
                  subject_type: subject.subject_type,
                  subject_id: subject.subject_id,
                  target: body.target,
                  effect: body.effect,
                  params: body.params,
                  enabled: item.draft.form.enabled,
                });
                if (!result.ok) {
                  setActiveDraftId(item.draft.id);
                  setError(result.error);
                  return;
                }
              } catch (e) {
                setActiveDraftId(item.draft.id);
                throw e;
              }
            }
          }
        }
      }

      router.push(returnHref);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("actions.saveFailed"));
    } finally {
      setSaving(false);
    }
  };

  const remove = async () => {
    if (target?.mode !== "edit") return;
    setSaving(true);
    setError(null);
    try {
      await deletePolicyRuleAction(target.policy.id);
      router.push(returnHref);
      router.refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : t("actions.deleteFailed"));
    } finally {
      setSaving(false);
    }
  };

  const title = isEdit
    ? t("titles.edit")
    : subjectType === "agent"
      ? t("titles.newAgent")
      : t("titles.newWorkspace");
  const hasAgentScopeEditor = subjectType === "agent" && !isEdit;
  const compiledSubjects = resolveSubjects();
  const compiledDrafts = drafts.map((draft) => ({
    draft,
    result: buildRuleBodies(draft.effect, draft.form),
  }));
  const firstInvalidDraft = compiledDrafts.find(
    (item) => "error" in item.result
  );
  const compiledError =
    compiledSubjects === null
      ? subjectType === "agent"
        ? t("summary.agentScopePending")
        : t("summary.workspaceScopeMissing")
      : firstInvalidDraft && "error" in firstInvalidDraft.result
        ? t("validation.ruleInvalid", {
            number:
              drafts.findIndex(
                (draft) => draft.id === firstInvalidDraft.draft.id
              ) + 1,
            effect: effectLabel(firstInvalidDraft.draft.effect),
            error: ruleErrorLabel(firstInvalidDraft.result.error),
          })
        : null;
  const compiledRuleCount =
    compiledSubjects && !firstInvalidDraft
      ? compiledSubjects.length *
        compiledDrafts.reduce(
          (sum, item) =>
            "bodies" in item.result ? sum + item.result.bodies.length : sum,
          0
        )
      : null;
  const enabledDraftCount = drafts.filter((draft) => draft.form.enabled).length;
  const compiledRows = [
    {
      label: t("summary.scope"),
      value:
        subjectType === "workspace"
          ? t("summary.workspace")
          : t("summary.agentCount", { count: selectedAgentIds.length }),
    },
    { label: t("summary.drafts"), value: String(drafts.length) },
    {
      label: t("summary.active"),
      value: t("summary.activeCount", {
        enabled: enabledDraftCount,
        total: drafts.length,
      }),
    },
    { label: t("summary.selected"), value: effectLabel(effect) },
    { label: t("summary.target"), value: previewTarget(effect, form) },
    { label: t("summary.params"), value: previewParams(effect, form) },
    {
      label: t("summary.rules"),
      value:
        compiledRuleCount === null
          ? t("summary.pending")
          : String(compiledRuleCount),
    },
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
                {t("sections.controlPlane")}
              </p>
              <h2 className="text-lg font-semibold text-foreground">{title}</h2>
              <p className="max-w-2xl text-sm text-muted-foreground">
                {t.rich("scope.policyDescription", {
                  scope: t(
                    subjectType === "workspace"
                      ? "scope.allAgentsInWorkspace"
                      : selectedAgents.length === 1
                        ? "scope.selectedAgent"
                        : "scope.selectedAgents"
                  ),
                  accessView: (chunks) => (
                    <Link
                      href="/policies?view=access"
                      className="text-primary underline-offset-4 hover:underline"
                    >
                      {chunks}
                    </Link>
                  ),
                })}
              </p>
            </div>
            <div className="min-w-[220px] border border-border/70 bg-background px-3 py-2">
              <p className="font-mono text-[10px] uppercase tracking-[0.14em] text-muted-foreground">
                {t("scope.target")}
              </p>
              {isEdit ? (
                <p className="mt-1 text-sm font-medium text-foreground">
                  {subjectType === "workspace"
                    ? t("scope.workspace")
                    : selectedAgents[0]?.name || target.policy.subject_id}
                </p>
              ) : (
                <div className="mt-2 inline-flex flex-wrap items-center gap-px border border-border/70 bg-muted/30 p-px">
                  {[
                    { value: "workspace" as const, label: t("scope.allAgentsOption") },
                    { value: "agents" as const, label: t("scope.selectedAgentsOption") },
                  ].map((option) => {
                    const active = scopeMode === option.value;
                    return (
                      <button
                        key={option.value}
                        type="button"
                        onClick={() => setScopeMode(option.value)}
                        className={cn(
                          "px-2.5 py-1 text-xs transition",
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
              )}
            </div>
          </div>
          {hasAgentScopeEditor && (
            <div className="mt-4 grid gap-3 border-t border-border/70 pt-4 lg:grid-cols-[minmax(240px,360px)_minmax(0,1fr)]">
              <div className="flex items-end gap-2">
                <div className="min-w-0 flex-1 space-y-1.5">
                  <Label htmlFor="policy-agent">{t("scope.agent")}</Label>
                  <AgentSelect
                    id="policy-agent"
                    agents={addableAgents}
                    value={agentToAddId}
                    onChange={setAgentToAddId}
                    placeholder={t("scope.selectAgentPlaceholder")}
                  />
                </div>
                <Button
                  type="button"
                  variant="outline"
                  size="icon"
                  disabled={!agentToAddId}
                  onClick={addSelectedAgent}
                  aria-label={t("scope.addAgent")}
                >
                  <Plus />
                </Button>
              </div>

              <div className="min-w-0 space-y-2">
                {selectedAgents.length > 0 ? (
                  selectedAgents.map((agent) => (
                    <div
                      key={agent.id}
                      className="flex items-center gap-2 border border-border/70 bg-background px-3 py-2"
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
                        aria-label={t("scope.removeAgent", {
                          agent: agent.name,
                        })}
                      >
                        <X />
                      </Button>
                    </div>
                  ))
                ) : (
                  <p className="border border-dashed border-border/70 px-3 py-3 text-sm text-muted-foreground">
                    {t("scope.addAgentsPrompt")}
                  </p>
                )}
              </div>
            </div>
          )}
        </div>

        <div className="relative px-5">
          <BlueprintSection code="01" title={t("sections.rules")}>
            <div className="space-y-3">
              <div className="grid gap-2 md:grid-cols-2">
                {drafts.map((draft, index) => {
                  const active = draft.id === activeDraftId;
                  const style = EFFECT_STYLES[draft.effect];
                  const Icon = style.icon;
                  return (
                    <div
                      key={draft.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => setActiveDraftId(draft.id)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          setActiveDraftId(draft.id);
                        }
                      }}
                      className={cn(
                        "cursor-pointer border border-border/70 bg-muted/20 px-3 py-2 transition-colors hover:bg-muted/30",
                        active && "shadow-[inset_2px_0_0_hsl(var(--primary))]"
                      )}
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="min-w-0">
                          <p className="font-mono text-[10px] uppercase tracking-[0.16em] text-muted-foreground">
                            {t("ruleIndex", { number: index + 1 })}
                          </p>
                          <div className="mt-1 flex items-center gap-2">
                            <Icon
                              className="h-4 w-4 text-muted-foreground"
                              strokeWidth={1.8}
                              aria-hidden
                            />
                            <span className="text-sm font-medium text-foreground">
                              {effectLabel(draft.effect)}
                            </span>
                            <span className="text-xs text-muted-foreground">
                              {draft.form.enabled
                                ? t("sections.enabled")
                                : t("sections.disabled")}
                            </span>
                          </div>
                          <p className="mt-1 truncate text-xs text-muted-foreground">
                            {previewParams(draft.effect, draft.form)}
                          </p>
                        </div>
                        {!isEdit && drafts.length > 1 && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="icon"
                            onClick={(event) => {
                              event.stopPropagation();
                              removeDraft(draft.id);
                            }}
                            aria-label={t("removeRule", {
                              number: index + 1,
                            })}
                          >
                            <X />
                          </Button>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>

              {!isEdit && (
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={addDraft}
                >
                  <Plus className="mr-1.5" />
                  {t("actions.addRule")}
                </Button>
              )}

              <div className="flex flex-wrap items-center justify-between gap-3 border border-border/70 bg-background px-3 py-3">
                <div className="min-w-0 space-y-2">
                  <Label>{t("sections.ruleType")}</Label>
                  <EffectSegmented
                    value={effect}
                    onChange={updateActiveEffect}
                    disabled={isEdit}
                  />
                  {isEdit && (
                    <p className="text-xs text-muted-foreground">
                      {t("sections.ruleTypeFixed")}
                    </p>
                  )}
                </div>
                <div className="flex items-center gap-3">
                  <Label htmlFor="policy-enabled">{t("sections.enabled")}</Label>
                  <Switch
                    id="policy-enabled"
                    checked={form.enabled}
                    onCheckedChange={(v) => update("enabled", v)}
                  />
                </div>
              </div>
            </div>
          </BlueprintSection>

          {/* Effect-specific fields */}
          {effect === "cap" && (
            <BlueprintSection code="02" title={t("sections.configuration")}>
              <div className="space-y-3 border border-border/70 bg-muted/20 p-4">
                <div className="space-y-1.5">
                  <Label htmlFor="cap-kind">{t("budget.type")}</Label>
                  <Select
                    value={form.capKind}
                    onValueChange={(v) => update("capKind", v as CapKind)}
                  >
                    <SelectTrigger id="cap-kind">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="spend">{t("budget.spend")}</SelectItem>
                      <SelectItem value="service">{t("budget.perService")}</SelectItem>
                      <SelectItem value="tokens">{t("budget.tokens")}</SelectItem>
                    </SelectContent>
                  </Select>
                </div>

                {form.capKind === "tokens" ? (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <NumberField
                      id="max-tokens"
                      label={t("budget.maxTokens")}
                      value={form.maxTokens}
                      onChange={(v) => update("maxTokens", v)}
                    />
                    <NumberField
                      id="max-tokens-call"
                      label={t("budget.maxTokensPerCall")}
                      value={form.maxTokensPerCall}
                      onChange={(v) => update("maxTokensPerCall", v)}
                    />
                  </div>
                ) : (
                  <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                    <MoneyField
                      id="cap-amount"
                      label={t("budget.amount")}
                      value={form.amountUsd}
                      onChange={(v) => update("amountUsd", v)}
                      currencySymbol={currencySymbol}
                    />
                    {form.capKind === "spend" && (
                      <div className="space-y-1.5">
                        <Label htmlFor="cap-period">{t("budget.period")}</Label>
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
                            <SelectItem value="month">{t("budget.perMonth")}</SelectItem>
                            <SelectItem value="run">{t("budget.perTask")}</SelectItem>
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
            <BlueprintSection code="02" title={t("sections.configuration")}>
              <div className="space-y-3 border border-border/70 bg-muted/20 p-4">
                <Label>{t("tools.deniedTools")}</Label>
                <ToolSelector
                  options={toolCatalog}
                  values={form.tools}
                  onChange={(next) => update("tools", next)}
                  emptyText={t("tools.noToolsAttached")}
                />
                <p className="text-xs text-muted-foreground">
                  {t("tools.everyCallHint")}
                </p>
                <p className="flex items-center gap-1 text-xs text-muted-foreground">
                  <LinkIcon className="h-3 w-3" />
                  {t("scope.toolAccessManaged")}{" "}
                  <Link
                    href="/policies?view=access"
                    className="text-primary underline-offset-4 hover:underline"
                  >
                    {t("scope.accessView")}
                  </Link>
                  .
                </p>
              </div>
            </BlueprintSection>
          )}

          {effect === "approval" && (
            <BlueprintSection code="02" title={t("sections.configuration")}>
              <div className="space-y-3 border border-border/70 bg-muted/20 p-4">
                <div className="space-y-1.5">
                  <Label>{t("tools.approvalRequiredTools")}</Label>
                  <ToolSelector
                    options={toolCatalog}
                    values={form.tools}
                    onChange={(next) => update("tools", next)}
                    emptyText={t("tools.noToolsAttached")}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t("tools.everyCallHint")}
                  </p>
                </div>
                <div className="space-y-1.5">
                  <Label>{t("approvers.label")}</Label>
                  <ApproverSelector
                    members={members}
                    values={form.approvers}
                    onChange={(next) => update("approvers", next)}
                  />
                  <p className="text-xs text-muted-foreground">
                    {t("approvers.emptyHelp")}
                  </p>
                </div>
              </div>
            </BlueprintSection>
          )}

          {effect === "safety" && (
            <BlueprintSection code="02" title={t("sections.configuration")}>
              <div className="space-y-3 border border-border/70 bg-muted/20 p-4">
                <div className="flex items-center justify-between">
                  <Label htmlFor="prompt-injection" className="font-normal">
                    {t("safety.promptInjection")}
                  </Label>
                  <Switch
                    id="prompt-injection"
                    checked={form.promptInjection}
                    onCheckedChange={(v) => update("promptInjection", v)}
                  />
                </div>
                <div className="flex items-center justify-between">
                  <Label htmlFor="output-sanitizer" className="font-normal">
                    {t("safety.outputSanitizer")}
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
              {t("actions.delete")}
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
              {t("actions.cancel")}
            </Button>
            <Button
              type="button"
              size="sm"
              isLoading={saving}
              disabled={saving}
              onClick={save}
            >
              {isEdit
                ? t("actions.saveRule")
                : t("actions.createRule", { count: drafts.length })}
            </Button>
          </div>
        </div>
      </section>

      <aside className="h-fit border border-border/70 bg-background">
        <div className="border-b border-border/70 bg-muted/20 px-4 py-3">
          <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
            {t("sections.impactRail")}
          </p>
        </div>
        <div className="flex items-center gap-2 border-b border-border/70 px-4 py-3">
          <span className="grid h-8 w-8 place-items-center border border-border/70 bg-muted/40">
            <UsersRound className="h-4 w-4 text-muted-foreground" />
          </span>
          <div>
            <h3 className="text-sm font-medium text-foreground">
              {t("scope.affectedAgents")}
            </h3>
            <p className="text-xs text-muted-foreground">
              {subjectType === "workspace"
                ? t("scope.workspaceAgentCount", { count: affectedAgents.length })
                : affectedAgents.length > 0
                  ? t("scope.selectedAgentCount", {
                      count: affectedAgents.length,
                    })
                  : t("scope.noAgentsSelected")}
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
                      {t("scope.agent")}
                    </span>
                  }
                />
              </div>
            ))
          ) : (
            <p className="border border-dashed border-border/70 px-3 py-3 text-sm text-muted-foreground">
              {subjectType === "workspace"
                ? t("scope.noAgentsInWorkspace")
                : t("scope.selectAgentPreview")}
            </p>
          )}
          {affectedAgents.length > 8 && (
            <p className="text-xs text-muted-foreground">
              {t("scope.moreAgents", {
                count: affectedAgents.length - 8,
              })}
            </p>
          )}
        </div>

        <div className="border-t border-border/70 p-4">
          <div className="mb-3 flex items-center justify-between gap-2">
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
              {t("summary.compiledOutput")}
            </p>
            {compiledError && (
              <span className="border border-dashed border-border/70 px-1.5 py-0.5 font-mono text-[10px] uppercase text-muted-foreground">
                {t("summary.pending")}
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
