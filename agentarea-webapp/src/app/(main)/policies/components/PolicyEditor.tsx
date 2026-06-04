"use client";

import { useEffect, useMemo, useState } from "react";
import { Link as LinkIcon, X } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";
import type { GovernancePolicy, PolicyDocument } from "@/types/policies";
import { EFFECT_STYLES } from "./policy-effects";

export type PolicyEditorTarget =
  | { mode: "create-workspace" }
  | { mode: "create-agent" }
  | { mode: "edit"; policy: GovernancePolicy };

interface AgentOption {
  id: string;
  name: string;
}

interface PolicyEditorProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  target: PolicyEditorTarget | null;
  agents: AgentOption[];
  workspaceId: string | null;
  onSaved: () => void;
}

// --- form state -----------------------------------------------------------

interface FormState {
  enabled: boolean;
  monthlySpendCap: string;
  runBudget: string;
  serviceBudget: string;
  maxTokens: string;
  maxTokensPerCall: string;
  requiresApproval: boolean;
  approvers: string[];
  escalationRules: string[];
  deniedTools: string[];
  promptInjectionDetection: boolean;
  outputSanitizer: boolean;
}

const EMPTY_FORM: FormState = {
  enabled: true,
  monthlySpendCap: "",
  runBudget: "",
  serviceBudget: "",
  maxTokens: "",
  maxTokensPerCall: "",
  requiresApproval: false,
  approvers: [],
  escalationRules: [],
  deniedTools: [],
  promptInjectionDetection: false,
  outputSanitizer: false,
};

function moneyToInput(value: unknown): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function numToInput(value: number | null | undefined): string {
  if (value === null || value === undefined) return "";
  return String(value);
}

function documentToForm(policy: GovernancePolicy): FormState {
  const doc = policy.document ?? {};
  return {
    enabled: policy.enabled,
    monthlySpendCap: moneyToInput(doc.budget?.monthly_spend_cap_usd),
    runBudget: moneyToInput(doc.budget?.run_budget_usd),
    serviceBudget: moneyToInput(doc.budget?.service_budget_usd),
    maxTokens: numToInput(doc.tokens?.max_tokens),
    maxTokensPerCall: numToInput(doc.tokens?.max_tokens_per_call),
    requiresApproval: Boolean(doc.approval?.requires_human_approval),
    approvers: doc.approval?.approvers ?? [],
    escalationRules: doc.approval?.escalation_rules ?? [],
    deniedTools: doc.tools?.denied ?? [],
    promptInjectionDetection: Boolean(
      doc.content_safety?.prompt_injection_detection_enabled
    ),
    outputSanitizer: Boolean(doc.content_safety?.output_sanitizer_enabled),
  };
}

// Parse a user-entered money value to a 2-decimal string, or null when blank/invalid.
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

// Assemble a clean PolicyDocument, omitting blank fields and empty sections.
function formToDocument(form: FormState): PolicyDocument {
  const doc: PolicyDocument = {};

  const monthly = parseMoney(form.monthlySpendCap);
  const run = parseMoney(form.runBudget);
  const service = parseMoney(form.serviceBudget);
  if (monthly !== null || run !== null || service !== null) {
    doc.budget = {};
    if (monthly !== null) doc.budget.monthly_spend_cap_usd = monthly;
    if (run !== null) doc.budget.run_budget_usd = run;
    if (service !== null) doc.budget.service_budget_usd = service;
  }

  const maxTokens = parseInt2(form.maxTokens);
  const maxTokensPerCall = parseInt2(form.maxTokensPerCall);
  if (maxTokens !== null || maxTokensPerCall !== null) {
    doc.tokens = {};
    if (maxTokens !== null) doc.tokens.max_tokens = maxTokens;
    if (maxTokensPerCall !== null)
      doc.tokens.max_tokens_per_call = maxTokensPerCall;
  }

  if (form.deniedTools.length > 0) {
    doc.tools = { denied: form.deniedTools };
  }

  if (form.requiresApproval) {
    doc.approval = { requires_human_approval: true };
    if (form.approvers.length > 0) doc.approval.approvers = form.approvers;
    if (form.escalationRules.length > 0)
      doc.approval.escalation_rules = form.escalationRules;
  }

  if (form.promptInjectionDetection || form.outputSanitizer) {
    doc.content_safety = {};
    if (form.promptInjectionDetection)
      doc.content_safety.prompt_injection_detection_enabled = true;
    if (form.outputSanitizer)
      doc.content_safety.output_sanitizer_enabled = true;
  }

  return doc;
}

// Loosely validate Keto subject refs (user:<id> | group:<id>#member, etc.).
const SUBJECT_REF_RE = /^[a-zA-Z]+:[^\s]+/;

// --- small building blocks ------------------------------------------------

function SectionHeader({
  effect,
  title,
  description,
}: {
  effect: keyof typeof EFFECT_STYLES;
  title: string;
  description?: string;
}) {
  const style = EFFECT_STYLES[effect];
  return (
    <div className="flex items-center gap-2">
      <span
        className={cn("h-2 w-2 shrink-0 rounded-full", style.dot)}
        aria-hidden
      />
      <span
        className={cn(
          "rounded px-1.5 py-0.5 text-[11px] font-medium",
          style.chip
        )}
      >
        {style.label}
      </span>
      <span className="text-sm font-semibold">{title}</span>
      {description && (
        <span className="text-xs text-muted-foreground">{description}</span>
      )}
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
    if (!values.includes(value)) {
      onChange([...values, value]);
    }
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
              className="inline-flex items-center gap-1 rounded-md border border-border bg-muted/50 px-2 py-0.5 font-mono text-xs"
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
          placeholder="optional"
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

// --- editor ---------------------------------------------------------------

export default function PolicyEditor({
  open,
  onOpenChange,
  target,
  agents,
  workspaceId,
  onSaved,
}: PolicyEditorProps) {
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [selectedAgentId, setSelectedAgentId] = useState<string>("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const isEdit = target?.mode === "edit";
  const scopeType = useMemo(() => {
    if (!target) return "workspace";
    if (target.mode === "edit") return target.policy.scope_type;
    if (target.mode === "create-agent") return "agent";
    return "workspace";
  }, [target]);

  // Reset form whenever the editor opens for a (new) target.
  useEffect(() => {
    if (!open || !target) return;
    if (target.mode === "edit") {
      setForm(documentToForm(target.policy));
      setSelectedAgentId(
        target.policy.scope_type === "agent" ? target.policy.scope_id : ""
      );
    } else {
      setForm(EMPTY_FORM);
      setSelectedAgentId("");
    }
    setError(null);
  }, [open, target]);

  const update = <K extends keyof FormState>(key: K, value: FormState[K]) =>
    setForm((prev) => ({ ...prev, [key]: value }));

  const resolveScopeId = (): string | null => {
    if (target?.mode === "edit") return target.policy.scope_id;
    if (scopeType === "agent") return selectedAgentId || null;
    return workspaceId;
  };

  const save = async (enabledOverride?: boolean) => {
    const scopeId = resolveScopeId();
    if (!scopeId) {
      setError(
        scopeType === "agent"
          ? "Select an agent for this policy."
          : "No workspace context available."
      );
      return;
    }

    const enabled = enabledOverride ?? form.enabled;
    const document = formToDocument({ ...form, enabled });

    setSaving(true);
    setError(null);
    try {
      const response = await fetch(
        `/api/proxy/v1/governance/policies/${scopeType}/${scopeId}`,
        {
          method: "PUT",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ document, enabled }),
        }
      );

      if (!response.ok) {
        let detail = `Save failed (${response.status})`;
        try {
          const body = (await response.json()) as { detail?: unknown };
          if (typeof body.detail === "string") detail = body.detail;
        } catch {
          // keep the status-based message
        }
        setError(detail);
        return;
      }

      onOpenChange(false);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save policy");
    } finally {
      setSaving(false);
    }
  };

  const scopeTitle = isEdit
    ? scopeType === "workspace"
      ? "Edit workspace policy"
      : "Edit agent policy"
    : scopeType === "agent"
      ? "New agent policy"
      : "New workspace policy";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[85vh] max-w-2xl overflow-y-auto">
        <DialogHeader>
          <DialogTitle>{scopeTitle}</DialogTitle>
          <DialogDescription>
            Restrictions defined here apply to{" "}
            {scopeType === "workspace"
              ? "every agent in this workspace"
              : "the selected agent"}
            . Tool access grants are managed in the Access view.
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-6 py-1">
          {/* Agent picker — only in agent create mode */}
          {target?.mode === "create-agent" && (
            <div className="space-y-1.5">
              <Label htmlFor="policy-agent">Agent</Label>
              <Select
                value={selectedAgentId}
                onValueChange={setSelectedAgentId}
              >
                <SelectTrigger id="policy-agent">
                  <SelectValue placeholder="Select an agent" />
                </SelectTrigger>
                <SelectContent>
                  {agents.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}

          {/* Cap */}
          <section className="space-y-3 rounded-lg border border-border p-4">
            <SectionHeader
              effect="cap"
              title="Spending & token caps"
              description="optional"
            />
            <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
              <MoneyField
                id="monthly-cap"
                label="Monthly spend cap"
                value={form.monthlySpendCap}
                onChange={(v) => update("monthlySpendCap", v)}
              />
              <MoneyField
                id="run-budget"
                label="Per-run budget"
                value={form.runBudget}
                onChange={(v) => update("runBudget", v)}
              />
              <MoneyField
                id="service-budget"
                label="Per-service budget"
                value={form.serviceBudget}
                onChange={(v) => update("serviceBudget", v)}
              />
            </div>
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
          </section>

          {/* Require approval */}
          <section className="space-y-3 rounded-lg border border-border p-4">
            <div className="flex items-center justify-between">
              <SectionHeader effect="approval" title="Require human approval" />
              <Switch
                checked={form.requiresApproval}
                onCheckedChange={(v) => update("requiresApproval", v)}
                aria-label="Require human approval"
              />
            </div>
            {form.requiresApproval && (
              <div className="space-y-3 pt-1">
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
                <div className="space-y-1.5">
                  <Label>Escalation rules</Label>
                  <TagInput
                    values={form.escalationRules}
                    onChange={(next) => update("escalationRules", next)}
                    placeholder="Add an escalation rule"
                  />
                </div>
              </div>
            )}
          </section>

          {/* Deny */}
          <section className="space-y-3 rounded-lg border border-border p-4">
            <SectionHeader
              effect="deny"
              title="Denied tools"
              description="optional"
            />
            <TagInput
              values={form.deniedTools}
              onChange={(next) => update("deniedTools", next)}
              placeholder="Add a tool name"
            />
            <p className="flex items-center gap-1 text-xs text-muted-foreground">
              <LinkIcon className="h-3 w-3" />
              Granting tool access is managed in the{" "}
              <a
                href="/policies?view=access"
                className="text-primary underline-offset-4 hover:underline"
              >
                Access view
              </a>
              .
            </p>
          </section>

          {/* Safety */}
          <section className="space-y-3 rounded-lg border border-border p-4">
            <SectionHeader effect="safety" title="Content safety" />
            <div className="flex items-center justify-between">
              <Label htmlFor="prompt-injection" className="font-normal">
                Prompt-injection detection
              </Label>
              <Switch
                id="prompt-injection"
                checked={form.promptInjectionDetection}
                onCheckedChange={(v) => update("promptInjectionDetection", v)}
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
          </section>

          {/* Enabled */}
          <div className="flex items-center justify-between rounded-lg border border-border p-4">
            <div>
              <Label htmlFor="policy-enabled">Policy enabled</Label>
              <p className="text-xs text-muted-foreground">
                Disabled policies are kept but not enforced.
              </p>
            </div>
            <Switch
              id="policy-enabled"
              checked={form.enabled}
              onCheckedChange={(v) => update("enabled", v)}
            />
          </div>
        </div>

        {error && (
          <p className="text-sm text-destructive" role="alert">
            {error}
          </p>
        )}

        <div className="flex items-center justify-between gap-2 border-t border-border pt-4">
          {isEdit && form.enabled ? (
            <Button
              type="button"
              variant="destructiveOutline"
              size="sm"
              disabled={saving}
              onClick={() => save(false)}
            >
              Disable
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
              onClick={() => onOpenChange(false)}
            >
              Cancel
            </Button>
            <Button
              type="button"
              size="sm"
              isLoading={saving}
              disabled={saving}
              onClick={() => save()}
            >
              Save policy
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
