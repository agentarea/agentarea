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

import React, { useEffect, useMemo, useReducer, useState } from "react";
import Image from "next/image";
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
  Plus,
  Puzzle,
  Send,
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
import ConfigSheet from "@/app/(main)/agents/create/components/ConfigSheet";
import ProviderConfigForm from "@/components/ProviderConfigForm/ProviderConfigForm";
import { cn } from "@/lib/utils";
import type {
  BundleAgent,
  BundleAutomation,
  BundleChannel,
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

// ── Edit state ──────────────────────────────────────────────────────────────
// Every choice the user makes in the wizard (which agents/connections/policies
// to keep, what to enable, setup values) lives in one reducer instead of a pile
// of useState setters. One state object, one set of typed actions, immutable
// updates — easy to extend and to reason about on install.

type EditState = {
  setupValues: Record<string, unknown>;
  agentOff: Set<string>; // excluded agents
  mcpOff: Set<string>; // globally excluded connections
  agentMcpOff: Record<string, Set<string>>; // connections detached per agent
  channelEnabled: Record<string, boolean>;
  autoEnabled: Record<string, boolean>;
  policyOff: Set<string>; // excluded policies
  policyEnabled: Record<string, boolean>;
};

const INITIAL_EDIT: EditState = {
  setupValues: {},
  agentOff: new Set(),
  mcpOff: new Set(),
  agentMcpOff: {},
  channelEnabled: {},
  autoEnabled: {},
  policyOff: new Set(),
  policyEnabled: {},
};

type EditAction =
  | {
      type: "init";
      setupValues: Record<string, unknown>;
      channelEnabled: Record<string, boolean>;
      autoEnabled: Record<string, boolean>;
      policyEnabled: Record<string, boolean>;
    }
  | { type: "setSetup"; key: string; value: unknown }
  | { type: "toggleAgent"; key: string; on: boolean }
  | { type: "toggleGlobalMcp"; key: string; on: boolean }
  | { type: "toggleAgentMcp"; agentKey: string; mcpKey: string; on: boolean }
  | { type: "toggleChannel"; key: string; on: boolean }
  | { type: "toggleAuto"; key: string; on: boolean }
  | { type: "togglePolicyInclude"; key: string; on: boolean }
  | { type: "togglePolicyEnabled"; key: string; on: boolean };

// Add/remove a key from a Set immutably (`present` = should it be in the set).
function withKey(set: Set<string>, key: string, present: boolean): Set<string> {
  const next = new Set(set);
  if (present) next.add(key);
  else next.delete(key);
  return next;
}

function editReducer(state: EditState, action: EditAction): EditState {
  switch (action.type) {
    case "init":
      return {
        ...INITIAL_EDIT,
        setupValues: action.setupValues,
        channelEnabled: action.channelEnabled,
        autoEnabled: action.autoEnabled,
        policyEnabled: action.policyEnabled,
      };
    case "setSetup":
      return { ...state, setupValues: { ...state.setupValues, [action.key]: action.value } };
    // `on` = included → the key is ABSENT from the "off" set.
    case "toggleAgent":
      return { ...state, agentOff: withKey(state.agentOff, action.key, !action.on) };
    case "toggleGlobalMcp":
      return { ...state, mcpOff: withKey(state.mcpOff, action.key, !action.on) };
    case "toggleAgentMcp": {
      const set = withKey(
        state.agentMcpOff[action.agentKey] ?? new Set(),
        action.mcpKey,
        !action.on
      );
      return { ...state, agentMcpOff: { ...state.agentMcpOff, [action.agentKey]: set } };
    }
    case "toggleChannel":
      return { ...state, channelEnabled: { ...state.channelEnabled, [action.key]: action.on } };
    case "toggleAuto":
      return { ...state, autoEnabled: { ...state.autoEnabled, [action.key]: action.on } };
    case "togglePolicyInclude":
      return { ...state, policyOff: withKey(state.policyOff, action.key, !action.on) };
    case "togglePolicyEnabled":
      return { ...state, policyEnabled: { ...state.policyEnabled, [action.key]: action.on } };
    default:
      return state;
  }
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
  const [providerSheetOpen, setProviderSheetOpen] = useState(false);

  // Edit state — one reducer keyed by the analyzed bundle, rebuilt into the
  // canonical object on install without mutating the preview.
  const [edit, dispatch] = useReducer(editReducer, INITIAL_EDIT);
  const {
    setupValues,
    agentOff,
    mcpOff,
    agentMcpOff,
    channelEnabled,
    autoEnabled,
    policyOff,
    policyEnabled,
  } = edit;

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
        dispatch({
          type: "init",
          setupValues: sv,
          channelEnabled: Object.fromEntries(
            (bundle.channels ?? []).map((c) => [c.key, Boolean(c.enabled)])
          ),
          autoEnabled: Object.fromEntries(
            (bundle.automations ?? []).map((a) => [a.key, Boolean(a.enabled)])
          ),
          policyEnabled: Object.fromEntries(
            (bundle.policies ?? []).map((p) => [p.key, p.enabled !== false])
          ),
        });
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

  const agents = useMemo(() => preview?.bundle.agents ?? [], [preview]);
  const mcps = useMemo(() => preview?.bundle.mcps ?? [], [preview]);
  const channels = useMemo(() => preview?.bundle.channels ?? [], [preview]);
  const automations = useMemo(() => preview?.bundle.automations ?? [], [preview]);
  const policies = useMemo(() => preview?.bundle.policies ?? [], [preview]);
  const setup = useMemo(() => preview?.setup ?? [], [preview]);

  // Tool-scoping is just governance policy: allow/deny rules targeting `tool:X`
  // bound to an agent. CapabilityGuard enforces them at runtime (default-deny
  // once an allowlist exists), so we surface the resulting scope per agent.
  const toolScope = (agentKey: string) => {
    const allowed: string[] = [];
    const denied: string[] = [];
    for (const p of policies) {
      if (p.subject !== agentKey) continue;
      const m = (p.target ?? "").match(/^tool:(.+)$/);
      if (!m || m[1] === "*") continue;
      if (p.effect === "allow") allowed.push(m[1]);
      else if (p.effect === "deny") denied.push(m[1]);
    }
    return { allowed, denied };
  };

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
      if (agentOff.has(a.key)) continue; // an excluded agent provisions nothing
      for (const ref of a.mcps ?? []) if (isAgentMcpOn(a.key, ref)) used.add(ref);
    }
    return used;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [agents, agentOff, mcpOff, agentMcpOff]);

  // Required setup fields that are still empty block the install (mirrors the
  // backend's required_setup_errors so we fail in the form, not after a POST).
  const missingRequired = useMemo(() => {
    return setup.filter((f) => {
      if (!f.required) return false;
      const v = setupValues[f.key];
      return v === undefined || v === null || v === "";
    });
  }, [setup, setupValues]);

  const setSetup = (key: string, value: unknown) => dispatch({ type: "setSetup", key, value });
  const toggleAgent = (key: string, on: boolean) => dispatch({ type: "toggleAgent", key, on });
  const toggleGlobalMcp = (key: string, on: boolean) =>
    dispatch({ type: "toggleGlobalMcp", key, on });
  const toggleAgentMcp = (agentKey: string, mcpKey: string, on: boolean) =>
    dispatch({ type: "toggleAgentMcp", agentKey, mcpKey, on });
  const toggleChannel = (key: string, on: boolean) =>
    dispatch({ type: "toggleChannel", key, on });
  const toggleAuto = (key: string, on: boolean) => dispatch({ type: "toggleAuto", key, on });
  const togglePolicyInclude = (key: string, on: boolean) =>
    dispatch({ type: "togglePolicyInclude", key, on });
  const togglePolicyEnabled = (key: string, on: boolean) =>
    dispatch({ type: "togglePolicyEnabled", key, on });

  // Re-pull workspace models after the quick provider setup sheet creates one,
  // so the new model is immediately selectable without leaving the wizard.
  async function refreshModels() {
    try {
      setModels(await listActiveModelInstancesAction());
    } catch {
      /* keep the current list on failure */
    }
  }

  async function install() {
    if (!preview) return;
    setPhase({ kind: "installing" });
    try {
      const finalAgents: BundleAgent[] = agents
        .filter((a) => !agentOff.has(a.key))
        .map((a) => ({
          ...a,
          mcps: (a.mcps ?? []).filter((ref) => isAgentMcpOn(a.key, ref)),
        }));
      const keptAgentKeys = new Set(finalAgents.map((a) => a.key));
      const finalMcps: BundleMcp[] = mcps.filter((m) => installedMcpKeys.has(m.key));
      // Drop channels/automations whose target agent is no longer being installed.
      const finalChannels: BundleChannel[] = channels
        .filter((c) => keptAgentKeys.has(c.agent))
        .map((c) => ({ ...c, enabled: channelEnabled[c.key] ?? false }));
      const finalAutomations: BundleAutomation[] = automations
        .filter((a) => keptAgentKeys.has(a.agent))
        .map((a) => ({ ...a, enabled: autoEnabled[a.key] ?? false }));
      const finalPolicies: BundlePolicy[] = policies
        .filter((p) => !policyOff.has(p.key))
        .map((p) => ({ ...p, enabled: policyEnabled[p.key] !== false }));

      const bundle = {
        ...preview.bundle,
        agents: finalAgents,
        mcps: finalMcps,
        channels: finalChannels,
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
            <Image src={iconUrl} alt={title} width={40} height={40} className="h-full w-full object-contain" />
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
                    onAddProvider={() => setProviderSheetOpen(true)}
                  />
                ))}
              </div>
            </Section>
          )}

          {/* Agents */}
          {agents.length > 0 && (
            <Section title="Agents" count={agents.length}>
              <p className="mb-2 text-xs text-muted-foreground">
                Choose which agents to install and which connections each one gets.
              </p>
              <div className="space-y-2">
                {agents.map((a) => {
                  const included = !agentOff.has(a.key);
                  return (
                    <div
                      key={a.key}
                      className={cn(
                        "rounded-lg border border-border/60 bg-muted/20 p-3",
                        !included && "opacity-60"
                      )}
                    >
                      <div className="flex items-center gap-2">
                        <AgentAvatar agent={{ id: a.key, name: a.name }} size="sm" />
                        <span className="min-w-0 flex-1 truncate text-sm font-medium">
                          {a.name}
                        </span>
                        <Switch
                          checked={included}
                          onCheckedChange={(c) => toggleAgent(a.key, c)}
                        />
                      </div>
                      {a.instruction && (
                        <p className="mt-2 line-clamp-2 text-xs text-muted-foreground">
                          {a.instruction}
                        </p>
                      )}
                      {included && (a.mcps ?? []).length > 0 && (
                        <div className="mt-3 space-y-1.5">
                          <p className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                            Connections
                          </p>
                          {(a.mcps ?? []).map((ref) => {
                            const conn = mcpByKey.get(ref);
                            const on = isAgentMcpOn(a.key, ref);
                            const globallyOff = mcpOff.has(ref);
                            return (
                              <label key={ref} className="flex items-center gap-2 text-sm">
                                <Checkbox
                                  checked={on}
                                  disabled={globallyOff}
                                  onCheckedChange={(c) =>
                                    toggleAgentMcp(a.key, ref, Boolean(c))
                                  }
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
                      {included &&
                        (() => {
                          const { allowed, denied } = toolScope(a.key);
                          if (allowed.length === 0 && denied.length === 0) return null;
                          return (
                            <div className="mt-3 flex flex-wrap items-center gap-1.5 rounded-md border border-amber-200 bg-amber-50 px-2 py-1.5 dark:border-amber-900/40 dark:bg-amber-950/20">
                              <ShieldCheck className="h-3.5 w-3.5 shrink-0 text-amber-600 dark:text-amber-400" />
                              {allowed.length > 0 ? (
                                <span className="text-[11px] text-amber-700 dark:text-amber-300">
                                  Tools locked to:{" "}
                                  <span className="font-medium">{allowed.join(", ")}</span> — all
                                  others blocked
                                </span>
                              ) : (
                                <span className="text-[11px] text-amber-700 dark:text-amber-300">
                                  Blocked tools:{" "}
                                  <span className="font-medium">{denied.join(", ")}</span>
                                </span>
                              )}
                            </div>
                          );
                        })()}
                    </div>
                  );
                })}
              </div>
            </Section>
          )}

          {/* Channels */}
          {channels.length > 0 && (
            <Section title="Channels" count={channels.length}>
              <p className="mb-2 text-xs text-muted-foreground">
                The agent receives and replies to messages here. Off by default — enable once
                the bot token is set and the bot points at the webhook URL shown after install.
              </p>
              <div className="space-y-2">
                {channels.map((c) => {
                  const secretLabels = Object.values(c.bindings ?? {})
                    .map((ref) => setupRefKey(ref))
                    .filter((k): k is string => Boolean(k))
                    .map((k) => setup.find((f) => f.key === k)?.label ?? k);
                  return (
                    <div
                      key={c.key}
                      className="flex items-start gap-3 rounded-lg border border-border/60 bg-muted/20 px-3 py-2.5"
                    >
                      <Send className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                      <div className="min-w-0 flex-1">
                        <p className="truncate text-sm font-medium">
                          {c.name}{" "}
                          <span className="font-normal capitalize text-muted-foreground">
                            · {c.type}
                          </span>
                        </p>
                        {secretLabels.length > 0 && (
                          <p className="text-[11px] text-muted-foreground">
                            Needs: {secretLabels.join(", ")}
                          </p>
                        )}
                      </div>
                      <Switch
                        checked={channelEnabled[c.key] ?? false}
                        onCheckedChange={(on) => toggleChannel(c.key, on)}
                      />
                    </div>
                  );
                })}
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
                      onCheckedChange={(c) => toggleAuto(a.key, c)}
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
                        onCheckedChange={(c) => togglePolicyInclude(p.key, Boolean(c))}
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
                        onCheckedChange={(c) => togglePolicyEnabled(p.key, c)}
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

      {/* Quick LLM provider setup — slides in from the right; on save we re-pull
          the model list so the new model is immediately pickable. */}
      <ConfigSheet
        title="Add a model provider"
        description="Connect an LLM provider to use its models in this bundle."
        triggerClassName="hidden"
        open={providerSheetOpen}
        onOpenChange={setProviderSheetOpen}
      >
        <ProviderConfigForm
          className="overflow-y-auto pb-6"
          onAfterSubmit={async () => {
            await refreshModels();
            setProviderSheetOpen(false);
          }}
          onCancel={() => setProviderSheetOpen(false)}
          isClear
          autoRedirect={false}
        />
      </ConfigSheet>
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
  onAddProvider,
}: {
  field: SetupField;
  value: unknown;
  isModel: boolean;
  models: WorkspaceModel[];
  onChange: (v: unknown) => void;
  onAddProvider: () => void;
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
          onAddProvider={onAddProvider}
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
  onAddProvider,
}: {
  models: WorkspaceModel[];
  value: string | undefined;
  suggested: string | null;
  onChange: (id: string) => void;
  onAddProvider: () => void;
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
                  <Image
                    src={selected.provider_icon_url}
                    alt=""
                    width={16}
                    height={16}
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
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      onAddProvider();
                    }}
                    className="block w-full underline"
                  >
                    Add a provider
                  </button>
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
                      <Image src={m.provider_icon_url} alt="" width={16} height={16} className="mr-2 h-4 w-4 rounded-sm" />
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
              {models.length > 0 && (
                <div className="border-t border-border/60 p-1">
                  <button
                    type="button"
                    onClick={() => {
                      setOpen(false);
                      onAddProvider();
                    }}
                    className="flex w-full items-center gap-2 rounded px-2 py-1.5 text-sm text-muted-foreground transition-colors hover:bg-muted/50"
                  >
                    <Plus className="h-4 w-4" />
                    Add provider
                  </button>
                </div>
              )}
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
          Done
        </Button>
      </div>
    </div>
  );
}
