"use client";

// Bundle install wizard. "Use this bundle" no longer installs on the first
// click — it opens this configure-then-install step so the user can review what
// a bundle creates and adjust it before committing:
//   • pick the model from their workspace (the bundle ships a suggested default)
//   • fill connection secrets / setup fields
//   • skip a connection entirely, or detach it from individual agents
//   • enable automations now or leave them off
//   • include/exclude and enable/disable each governance policy
// The backend already supports this: /analyze returns an editable canonical
// bundle, and /install takes a (possibly edited) bundle + setup values. We edit
// the analyzed bundle in place and send the result.

import React, { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import {
  AlertTriangle,
  Check,
  CheckCircle2,
  ChevronLeft,
  ChevronsUpDown,
  Clock,
  Loader2,
  Plug,
  Puzzle,
  ShieldCheck,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "@/components/ui/command";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { Switch } from "@/components/ui/switch";
import { StartAgentButton } from "@/components/ui/start-agent-button";
import { AgentAvatar } from "@/components/AgentAvatar";
import { cn } from "@/lib/utils";
import type {
  BundleAgent,
  BundleAutomation,
  BundleMcp,
  BundlePolicy,
  ImportPreview,
  InstallResult,
  SetupField,
} from "@/api/client/types.gen";
import {
  analyzeBundleAction,
  installBundleAction,
  listActiveModelInstancesAction,
  type WorkspaceModel,
} from "./actions";
import { str } from "./catalog-data";

// ${setup.<key>} reference used by an agent's model / a connection binding.
const SETUP_REF = /^\$\{setup\.([a-zA-Z0-9_]+)\}$/;

function setupRefKey(value: string | null | undefined): string | null {
  const m = (value ?? "").match(SETUP_REF);
  return m ? m[1] : null;
}

type Phase =
  | { kind: "analyzing" }
  | { kind: "form" }
  | { kind: "installing" }
  | { kind: "done"; result: InstallResult }
  | { kind: "error"; message: string };

export function BundleInstallWizard({
  source,
  title,
  iconUrl,
  onBack,
}: {
  source: string;
  title: string;
  iconUrl: string | null;
  onBack: () => void;
}) {
  const [phase, setPhase] = useState<Phase>({ kind: "analyzing" });
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [models, setModels] = useState<WorkspaceModel[]>([]);

  // Edit state — kept separate from the analyzed bundle so we can rebuild the
  // canonical object on install without mutating the preview.
  const [setupValues, setSetupValues] = useState<Record<string, unknown>>({});
  const [mcpOff, setMcpOff] = useState<Set<string>>(new Set()); // globally excluded connections
  const [agentMcpOff, setAgentMcpOff] = useState<Record<string, Set<string>>>({}); // per-agent detached
  const [autoEnabled, setAutoEnabled] = useState<Record<string, boolean>>({});
  const [policyOff, setPolicyOff] = useState<Set<string>>(new Set());
  const [policyEnabled, setPolicyEnabled] = useState<Record<string, boolean>>({});

  useEffect(() => {
    let active = true;
    setPhase({ kind: "analyzing" });
    Promise.all([
      analyzeBundleAction({ source }),
      listActiveModelInstancesAction().catch(() => [] as WorkspaceModel[]),
    ])
      .then(([pv, ms]) => {
        if (!active) return;
        setPreview(pv);
        setModels(ms);
        const bundle = pv.bundle;
        const sv: Record<string, unknown> = {};
        for (const f of pv.setup ?? []) {
          if (f.default !== undefined && f.default !== null) sv[f.key] = f.default;
        }
        setSetupValues(sv);
        setAutoEnabled(
          Object.fromEntries((bundle.automations ?? []).map((a) => [a.key, Boolean(a.enabled)]))
        );
        setPolicyEnabled(
          Object.fromEntries(
            (bundle.policies ?? []).map((p) => [p.key, p.enabled !== false])
          )
        );
        setPhase({ kind: "form" });
      })
      .catch((e: unknown) => {
        if (!active) return;
        setPhase({ kind: "error", message: e instanceof Error ? e.message : "Analyze failed" });
      });
    return () => {
      active = false;
    };
  }, [source]);

  // Which setup keys feed an agent's model → render those as a workspace model
  // picker instead of a plain text field.
  const modelFieldKeys = useMemo(() => {
    const keys = new Set<string>();
    for (const a of preview?.bundle.agents ?? []) {
      const k = setupRefKey(a.model);
      if (k) keys.add(k);
    }
    return keys;
  }, [preview]);

  const agents = preview?.bundle.agents ?? [];
  const mcps = preview?.bundle.mcps ?? [];
  const automations = preview?.bundle.automations ?? [];
  const policies = preview?.bundle.policies ?? [];
  const setup = preview?.setup ?? [];

  const mcpByKey = useMemo(() => {
    const m = new Map<string, BundleMcp>();
    for (const x of mcps) m.set(x.key, x);
    return m;
  }, [mcps]);

  // A connection ends up installed only if it isn't globally excluded and at
  // least one agent still attaches it.
  const isAgentMcpOn = (agentKey: string, mcpKey: string) =>
    !mcpOff.has(mcpKey) && !(agentMcpOff[agentKey]?.has(mcpKey) ?? false);

  const installedMcpKeys = useMemo(() => {
    const used = new Set<string>();
    for (const a of agents) {
      for (const ref of a.mcps ?? []) if (isAgentMcpOn(a.key, ref)) used.add(ref);
    }
    return used;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, mcpOff, agentMcpOff]);

  // Required setup fields that are still empty block the install (mirrors the
  // backend's required_setup_errors so we fail in the form, not after a POST).
  const missingRequired = useMemo(() => {
    return setup.filter((f) => {
      if (!f.required) return false;
      const v = setupValues[f.key];
      return v === undefined || v === null || v === "";
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [setup, setupValues]);

  function setSetup(key: string, value: unknown) {
    setSetupValues((prev) => ({ ...prev, [key]: value }));
  }

  function toggleGlobalMcp(key: string, on: boolean) {
    setMcpOff((prev) => {
      const next = new Set(prev);
      if (on) next.delete(key);
      else next.add(key);
      return next;
    });
  }

  function toggleAgentMcp(agentKey: string, mcpKey: string, on: boolean) {
    setAgentMcpOff((prev) => {
      const next = { ...prev };
      const set = new Set(next[agentKey] ?? []);
      if (on) set.delete(mcpKey);
      else set.add(mcpKey);
      next[agentKey] = set;
      return next;
    });
  }

  async function install() {
    if (!preview) return;
    setPhase({ kind: "installing" });
    try {
      const finalAgents: BundleAgent[] = agents.map((a) => ({
        ...a,
        mcps: (a.mcps ?? []).filter((ref) => isAgentMcpOn(a.key, ref)),
      }));
      const finalMcps: BundleMcp[] = mcps.filter((m) => installedMcpKeys.has(m.key));
      const finalAutomations: BundleAutomation[] = automations.map((a) => ({
        ...a,
        enabled: autoEnabled[a.key] ?? false,
      }));
      const finalPolicies: BundlePolicy[] = policies
        .filter((p) => !policyOff.has(p.key))
        .map((p) => ({ ...p, enabled: policyEnabled[p.key] !== false }));

      const bundle = {
        ...preview.bundle,
        agents: finalAgents,
        mcps: finalMcps,
        automations: finalAutomations,
        policies: finalPolicies,
      };

      const result = await installBundleAction({
        bundle: bundle as never,
        setup_values: setupValues,
      });
      setPhase({ kind: "done", result });
    } catch (e) {
      setPhase({ kind: "error", message: e instanceof Error ? e.message : "Install failed" });
    }
  }

  const blockIssues = (preview?.issues ?? []).filter((i) => i.severity === "block");
  const warnIssues = (preview?.issues ?? []).filter((i) => i.severity === "warn");

  return (
    <div className="max-w-2xl space-y-6">
      <button
        onClick={onBack}
        className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
      >
        <ChevronLeft className="h-4 w-4" />
        Back
      </button>

      <div className="flex items-center gap-3">
        {iconUrl ? (
          <span className="flex h-10 w-10 items-center justify-center overflow-hidden rounded-lg border border-border/60 bg-white p-1.5 dark:bg-zinc-800">
            <img src={iconUrl} alt={title} className="h-full w-full object-contain" />
          </span>
        ) : null}
        <div>
          <h2 className="text-xl font-semibold tracking-tight">Set up {title}</h2>
          <p className="text-sm text-muted-foreground">
            Review and adjust what this bundle adds before installing.
          </p>
        </div>
      </div>

      {phase.kind === "analyzing" && (
        <div className="flex items-center gap-2 py-8 text-sm text-muted-foreground">
          <Loader2 className="h-4 w-4 animate-spin" />
          Analyzing bundle…
        </div>
      )}

      {phase.kind === "error" && (
        <div className="flex items-start gap-2 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30">
          <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
          {phase.message}
        </div>
      )}

      {phase.kind === "done" && <InstallSummary result={phase.result} onBack={onBack} />}

      {(phase.kind === "form" || phase.kind === "installing") && preview && (
        <div className="space-y-7">
          {blockIssues.length > 0 && (
            <div className="space-y-1 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-900/50 dark:bg-red-950/30">
              {blockIssues.map((i, idx) => (
                <p key={idx} className="flex items-start gap-2">
                  <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
                  {i.message}
                </p>
              ))}
            </div>
          )}
          {warnIssues.length > 0 && (
            <div className="space-y-1 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-xs text-amber-700 dark:border-amber-900/50 dark:bg-amber-950/30">
              {warnIssues.map((i, idx) => (
                <p key={idx}>{i.message}</p>
              ))}
            </div>
          )}

          {/* Setup fields (models, secrets, options) */}
          {setup.length > 0 && (
            <Section title="Configuration">
              <div className="space-y-4">
                {setup.map((f) => (
                  <SetupFieldInput
                    key={f.key}
                    field={f}
                    value={setupValues[f.key]}
                    isModel={modelFieldKeys.has(f.key)}
                    models={models}
                    onChange={(v) => setSetup(f.key, v)}
                  />
                ))}
              </div>
            </Section>
          )}

          {/* Agents */}
          {agents.length > 0 && (
            <Section title="Agents" count={agents.length}>
              <div className="space-y-2">
                {agents.map((a) => (
                  <div
                    key={a.key}
                    className="rounded-lg border border-border/60 bg-muted/20 p-3"
                  >
                    <div className="flex items-center gap-2">
                      <AgentAvatar agent={{ id: a.key, name: a.name }} size="sm" />
                      <span className="min-w-0 flex-1 truncate text-sm font-medium">{a.name}</span>
                    </div>
                    {a.instruction && (
                      <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
                        {a.instruction}
                      </p>
                    )}
                    {(a.mcps ?? []).length > 0 && (
                      <div className="mt-3 space-y-1.5">
                        <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                          Connections
                        </p>
                        {(a.mcps ?? []).map((ref) => {
                          const conn = mcpByKey.get(ref);
                          const on = isAgentMcpOn(a.key, ref);
                          const globallyOff = mcpOff.has(ref);
                          return (
                            <label
                              key={ref}
                              className="flex items-center gap-2 text-sm"
                            >
                              <Checkbox
                                checked={on}
                                disabled={globallyOff}
                                onCheckedChange={(c) => toggleAgentMcp(a.key, ref, Boolean(c))}
                              />
                              <Plug className="h-3.5 w-3.5 text-muted-foreground" />
                              <span className="min-w-0 flex-1 truncate">
                                {conn?.name ?? ref}
                              </span>
                              {globallyOff && (
                                <span className="text-[11px] text-muted-foreground">
                                  not installed
                                </span>
                              )}
                            </label>
                          );
                        })}
                      </div>
                    )}
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Connections */}
          {mcps.length > 0 && (
            <Section title="Connections" count={mcps.length}>
              <p className="mb-2 text-xs text-muted-foreground">
                Turn a connection off to skip provisioning it. Connections are authorized
                after install.
              </p>
              <div className="space-y-2">
                {mcps.map((m) => {
                  const on = !mcpOff.has(m.key);
                  const secretKeys = Object.values(m.bindings ?? {})
                    .map((ref) => setupRefKey(ref))
                    .filter((k): k is string => Boolean(k));
                  const secretLabels = secretKeys
                    .map((k) => setup.find((f) => f.key === k)?.label ?? k)
                    .filter(Boolean);
                  return (
                    <div
                      key={m.key}
                      className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5"
                    >
                      <Plug className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">{m.name}</p>
                        {secretLabels.length > 0 && (
                          <p className="text-[11px] text-muted-foreground">
                            Needs: {secretLabels.join(", ")}
                          </p>
                        )}
                      </div>
                      <Switch checked={on} onCheckedChange={(c) => toggleGlobalMcp(m.key, c)} />
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {/* Automations */}
          {automations.length > 0 && (
            <Section title="Automations" count={automations.length}>
              <p className="mb-2 text-xs text-muted-foreground">
                Off by default — enable once connections are authorized.
              </p>
              <div className="space-y-2">
                {automations.map((a) => (
                  <div
                    key={a.key}
                    className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5"
                  >
                    <Clock className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{a.key}</p>
                      <p className="truncate text-[11px] text-muted-foreground">
                        {a.cron} · {a.prompt}
                      </p>
                    </div>
                    <Switch
                      checked={autoEnabled[a.key] ?? false}
                      onCheckedChange={(c) =>
                        setAutoEnabled((prev) => ({ ...prev, [a.key]: c }))
                      }
                    />
                  </div>
                ))}
              </div>
            </Section>
          )}

          {/* Policies */}
          {policies.length > 0 && (
            <Section title="Policies" count={policies.length}>
              <p className="mb-2 text-xs text-muted-foreground">
                Governance rules applied at runtime. Uncheck to skip, or toggle enabled.
              </p>
              <div className="space-y-2">
                {policies.map((p) => {
                  const included = !policyOff.has(p.key);
                  return (
                    <div
                      key={p.key}
                      className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5"
                    >
                      <Checkbox
                        className="mt-0.5"
                        checked={included}
                        onCheckedChange={(c) =>
                          setPolicyOff((prev) => {
                            const next = new Set(prev);
                            if (c) next.delete(p.key);
                            else next.add(p.key);
                            return next;
                          })
                        }
                      />
                      <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                      <div className="min-w-0 flex-1">
                        <p className="text-sm font-medium">
                          {p.message || `${p.effect} · ${p.target}`}
                        </p>
                        <p className="text-[11px] text-muted-foreground">
                          <span className="capitalize">{p.effect}</span> · {p.target}
                          {p.subject && p.subject !== "workspace" ? ` · ${p.subject}` : ""}
                        </p>
                      </div>
                      <Switch
                        checked={included && policyEnabled[p.key] !== false}
                        disabled={!included}
                        onCheckedChange={(c) =>
                          setPolicyEnabled((prev) => ({ ...prev, [p.key]: c }))
                        }
                      />
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {/* Footer / commit */}
          <div className="flex flex-col gap-2 border-t border-border/60 pt-5">
            {missingRequired.length > 0 && (
              <p className="text-xs text-amber-600 dark:text-amber-400">
                Fill required fields: {missingRequired.map((f) => f.label).join(", ")}
              </p>
            )}
            <div className="flex items-center gap-2">
              <StartAgentButton
                size="xs"
                onClick={install}
                isLoading={phase.kind === "installing"}
                disabled={blockIssues.length > 0 || missingRequired.length > 0}
              >
                Install bundle
              </StartAgentButton>
              <Button variant="ghost" size="sm" onClick={onBack}>
                Cancel
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

function Section({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-2 flex items-center gap-1.5 text-[11px] font-semibold uppercase tracking-wide text-muted-foreground">
        {title}
        {count !== undefined && <span className="tabular-nums">({count})</span>}
      </div>
      {children}
    </div>
  );
}

function SetupFieldInput({
  field,
  value,
  isModel,
  models,
  onChange,
}: {
  field: SetupField;
  value: unknown;
  isModel: boolean;
  models: WorkspaceModel[];
  onChange: (v: unknown) => void;
}) {
  const id = `setup-${field.key}`;
  const type = field.type ?? "string";

  return (
    <div className="space-y-1.5">
      <Label htmlFor={id} className="text-sm">
        {field.label}
        {field.required && <span className="ml-0.5 text-red-500">*</span>}
      </Label>
      {isModel ? (
        <ModelPicker
          models={models}
          value={typeof value === "string" ? value : undefined}
          suggested={str(field.default)}
          onChange={onChange}
        />
      ) : type === "boolean" ? (
        <div className="flex items-center gap-2">
          <Switch checked={Boolean(value)} onCheckedChange={(c) => onChange(c)} />
          <span className="text-sm text-muted-foreground">{field.help}</span>
        </div>
      ) : type === "select" ? (
        <select
          id={id}
          value={typeof value === "string" ? value : ""}
          onChange={(e) => onChange(e.target.value)}
          className="h-9 w-full rounded-md border border-input bg-background px-3 text-sm"
        >
          <option value="" disabled>
            Select…
          </option>
          {(field.options ?? []).map((opt) => (
            <option key={opt} value={opt}>
              {opt}
            </option>
          ))}
        </select>
      ) : (
        <Input
          id={id}
          type={type === "secret" ? "password" : type === "number" ? "number" : "text"}
          value={value === undefined || value === null ? "" : String(value)}
          placeholder={field.help ?? ""}
          onChange={(e) =>
            onChange(type === "number" ? e.target.valueAsNumber || e.target.value : e.target.value)
          }
        />
      )}
      {field.help && type !== "boolean" && !isModel && (
        <p className="text-[11px] text-muted-foreground">{field.help}</p>
      )}
    </div>
  );
}

function ModelPicker({
  models,
  value,
  suggested,
  onChange,
}: {
  models: WorkspaceModel[];
  value: string | undefined;
  suggested: string | null;
  onChange: (id: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const selected = models.find((m) => m.id === value) ?? null;

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger asChild>
          <Button
            variant="outline"
            role="combobox"
            className="w-full justify-between font-normal"
          >
            {selected ? (
              <span className="flex min-w-0 items-center gap-2">
                {selected.provider_icon_url && (
                  <img
                    src={selected.provider_icon_url}
                    alt=""
                    className="h-4 w-4 rounded-sm"
                  />
                )}
                <span className="truncate">
                  {selected.model_display_name || selected.model_name}
                </span>
              </span>
            ) : (
              <span className="truncate text-muted-foreground">Select a model</span>
            )}
            <ChevronsUpDown className="h-4 w-4 shrink-0 opacity-50" />
          </Button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-[var(--radix-popover-trigger-width)] p-0"
        >
          <Command>
            <CommandInput placeholder="Search models…" />
            <CommandList>
              <CommandEmpty>
                <div className="space-y-1.5 py-3 text-center text-sm text-muted-foreground">
                  <p>No models configured.</p>
                  <Link href="/admin/provider-configs" className="block underline">
                    Add a provider
                  </Link>
                </div>
              </CommandEmpty>
              <CommandGroup>
                {models.map((m) => (
                  <CommandItem
                    key={m.id}
                    value={`${m.model_display_name ?? ""} ${m.model_name} ${m.provider_name}`}
                    onSelect={() => {
                      onChange(m.id);
                      setOpen(false);
                    }}
                  >
                    {m.provider_icon_url && (
                      <img src={m.provider_icon_url} alt="" className="mr-2 h-4 w-4 rounded-sm" />
                    )}
                    <span className="min-w-0 flex-1 truncate">
                      {m.model_display_name || m.model_name}
                    </span>
                    <span className="ml-2 shrink-0 text-xs text-muted-foreground">
                      {m.provider_name}
                    </span>
                    {value === m.id && <Check className="ml-2 h-4 w-4 shrink-0" />}
                  </CommandItem>
                ))}
              </CommandGroup>
            </CommandList>
          </Command>
        </PopoverContent>
      </Popover>
      {!selected && suggested && (
        <p className="text-[11px] text-muted-foreground">
          Defaults to <span className="font-medium">{suggested}</span> if not changed.
        </p>
      )}
    </>
  );
}

function InstallSummary({ result, onBack }: { result: InstallResult; onBack: () => void }) {
  const entities = result.entities ?? [];
  const created = entities.filter((e) => e.action === "created");
  const reused = entities.filter((e) => e.action === "reused");
  const skipped = entities.filter((e) => e.action === "skipped");

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-900/50 dark:bg-emerald-950/30">
        <CheckCircle2 className="h-4 w-4 shrink-0" />
        Installed {result.bundle_name} — {created.length} created
        {reused.length > 0 ? `, ${reused.length} reused` : ""}
        {skipped.length > 0 ? `, ${skipped.length} skipped` : ""}.
      </div>

      <ul className="divide-y divide-border/60 overflow-hidden rounded-lg border border-border/60 text-sm">
        {entities.map((e) => (
          <li key={`${e.kind}-${e.key}`} className="flex items-center gap-2 px-3 py-2">
            <Puzzle className="h-3.5 w-3.5 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate">{e.name}</span>
            <Badge variant="light" size="sm" className="capitalize">
              {e.kind}
            </Badge>
            <Badge
              variant={e.action === "created" ? "blue" : "light"}
              size="sm"
              className="capitalize"
            >
              {e.action}
            </Badge>
          </li>
        ))}
      </ul>

      <div className="flex items-center gap-2">
        <Button asChild size="sm">
          <Link href="/agents">Go to Agents</Link>
        </Button>
        <Button variant="ghost" size="sm" onClick={onBack}>
          Back to catalog
        </Button>
      </div>
    </div>
  );
}
