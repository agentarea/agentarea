"use client";

// One bundle, shown the same way before and while it is configured: what the
// bundle creates, section by section, on the same overview cards the agent page
// uses. "Use this bundle" does not swap in a different screen — the same
// sections gain their switches, the model pickers and the setup fields, and a
// footer that installs exactly what is on screen.
import React, { useEffect, useMemo, useReducer, useState } from "react";
import { useTranslations } from "next-intl";
import { Puzzle, Send, ShieldCheck, SlidersHorizontal } from "lucide-react";
import type {
  BundleAgent,
  ImportPreview,
  InstallResult,
  ModelInstanceResponse,
  SetupField,
} from "@/api/client/types.gen";
import { EFFECT_STYLES } from "@/app/w/[workspace]/(main)/policies/components/policy-effects";
import { policyToRule } from "@/app/w/[workspace]/(main)/policies/components/policy-rules";
import { describeCronExpression } from "@/app/w/[workspace]/(main)/triggers/components/triggerDisplay";
import { AdminOnlyHint } from "@/components/AdminOnlyState";
import { AgentAvatar } from "@/components/AgentAvatar";
import ConfigSheet from "@/components/ConfigSheet";
import FormError from "@/components/FormError";
import {
  FactRow,
  SectionCard,
  SectionCardHead,
  SoftTile,
} from "@/components/Overview/OverviewCard";
import ProviderConfigForm from "@/components/ProviderConfigForm/ProviderConfigForm";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { ProviderModelSelector } from "@/components/ui/provider-model-selector";
import { StartAgentButton } from "@/components/ui/start-agent-button";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { Switch } from "@/components/ui/switch";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
import Link from "@/components/WorkspaceLink";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";
import { agentPath } from "@/types";
import {
  analyzeBundleAction,
  installBundleAction,
  listActiveModelInstancesAction,
} from "./actions";
import {
  agentsWithoutModel,
  boundSetupKeys,
  buildInstallRequest,
  bundleEditReducer,
  bundlePolicyAsPolicy,
  initialEdit,
  installedMcpKeys,
  isAgentMcpOn,
  missingRequiredSetup,
  openIssues,
  setupFieldPlacement,
  suggestedModel,
  type BundleEdit,
  type BundleEditAction,
} from "./bundle-plan";

type Load =
  | { kind: "loading" }
  | { kind: "error"; message: string }
  | { kind: "ready"; preview: ImportPreview };

type Install =
  | { kind: "idle" }
  | { kind: "installing" }
  | { kind: "error"; message: string }
  | { kind: "done"; result: InstallResult };

export function BundlePlan({
  source,
  configuring,
  onCancel,
}: {
  source: string;
  configuring: boolean;
  onCancel: () => void;
}) {
  const { canAdminister } = useViewerCapabilities();
  const router = useWorkspaceRouter();
  const t = useTranslations("BundleInstall");
  const tCommon = useTranslations("Common");
  const [load, setLoad] = useState<Load>({ kind: "loading" });
  const [models, setModels] = useState<ModelInstanceResponse[]>([]);
  const [modelsError, setModelsError] = useState<string | null>(null);
  const [install, setInstall] = useState<Install>({ kind: "idle" });
  const [providerSheetOpen, setProviderSheetOpen] = useState(false);
  const [edit, dispatch] = useReducer(bundleEditReducer, null, () => ({
    setupValues: {},
    agentModels: {},
    agentOff: new Set<string>(),
    mcpOff: new Set<string>(),
    agentMcpOff: {},
    channelEnabled: {},
    autoEnabled: {},
    policyOff: new Set<string>(),
    policyEnabled: {},
  }));

  useEffect(() => {
    let active = true;
    setLoad({ kind: "loading" });
    Promise.all([
      analyzeBundleAction({ source }),
      listActiveModelInstancesAction().then(
        (result) => ({
          ms: result.data ?? [],
          error: result.error
            ? apiErrorMessage(result, t("modelsLoadFailed"))
            : null,
        }),
        (error: unknown) => {
          console.error("Failed to load workspace models", error);
          return {
            ms: [] as ModelInstanceResponse[],
            error: `${t("modelsLoadFailed")}: ${formatApiError(error)}`,
          };
        }
      ),
    ])
      .then(([analyzed, { ms, error }]) => {
        if (!active) return;
        if (analyzed.error || !analyzed.data) {
          setLoad({
            kind: "error",
            message: apiErrorMessage(analyzed, t("analyzeFailed")),
          });
          return;
        }
        setModels(ms);
        setModelsError(error);
        dispatch({ type: "reset", edit: initialEdit(analyzed.data, ms) });
        setLoad({ kind: "ready", preview: analyzed.data });
      })
      .catch((e: unknown) => {
        if (!active) return;
        console.error("Failed to analyze bundle", e);
        setLoad({
          kind: "error",
          message: `${t("analyzeFailed")}: ${formatApiError(e)}`,
        });
      });
    return () => {
      active = false;
    };
  }, [source, t]);

  // Re-pull workspace models after the quick provider sheet creates one, so it
  // is pickable without leaving the page.
  async function refreshModels() {
    try {
      const result = await listActiveModelInstancesAction();
      if (result.error || !result.data) {
        setModelsError(apiErrorMessage(result, t("modelsLoadFailed")));
        return;
      }
      setModels(result.data);
      setModelsError(null);
    } catch (error) {
      console.error("Failed to reload workspace models", error);
      setModelsError(`${t("modelsLoadFailed")}: ${formatApiError(error)}`);
    }
  }

  if (load.kind === "loading") {
    return (
      <StatusIndicator kind="running" size="sm" className="py-8 text-sm">
        Reading bundle…
      </StatusIndicator>
    );
  }
  if (load.kind === "error") {
    return <FormError>{load.message}</FormError>;
  }

  const preview = load.preview;

  async function runInstall() {
    setInstall({ kind: "installing" });
    try {
      const installed = await installBundleAction(
        buildInstallRequest(preview, edit, canAdminister)
      );
      if (installed.error || !installed.data) {
        setInstall({
          kind: "error",
          message: apiErrorMessage(installed, t("installFailed")),
        });
        return;
      }
      // A bundle that ships an agent is started, not just installed: open the
      // first one on its new-task page. Agentless bundles get the summary.
      const agent = (installed.data.entities ?? []).find(
        (e) => e.kind === "agent" && e.id
      );
      if (agent?.id) {
        router.push(agentPath({ id: agent.id }, "/new-task"));
        router.refresh();
        return;
      }
      setInstall({ kind: "done", result: installed.data });
    } catch (e) {
      console.error("Failed to install bundle", e);
      setInstall({
        kind: "error",
        message: `${t("installFailed")}: ${formatApiError(e)}`,
      });
    }
  }

  if (install.kind === "done") {
    return (
      <InstallSummary
        result={install.result}
        onBack={() => {
          setInstall({ kind: "idle" });
          onCancel();
        }}
      />
    );
  }

  const issues = openIssues(preview, edit);
  const blocking = issues.filter((i) => i.severity === "block");
  const warnings = issues.filter((i) => i.severity === "warn");
  const missing = missingRequiredSetup(preview, edit);
  const modelless = agentsWithoutModel(preview, edit);
  const agentsKept = (preview.bundle.agents ?? []).some(
    (a) => !edit.agentOff.has(a.key)
  );

  return (
    <div className="space-y-4">
      {blocking.length > 0 && (
        <FormError>
          {blocking.map((i) => (
            <span key={i.message} className="block">
              {i.message}
            </span>
          ))}
        </FormError>
      )}
      {warnings.map((i) => (
        <StatusIndicator
          key={i.message}
          kind="attention"
          size="sm"
          className="text-xs"
        >
          {i.message}
        </StatusIndicator>
      ))}

      <BundleSections
        preview={preview}
        models={models}
        modelsError={modelsError}
        edit={edit}
        dispatch={configuring ? dispatch : undefined}
        canAdminister={canAdminister}
        onAddProvider={() => setProviderSheetOpen(true)}
        onRetryModels={refreshModels}
      />

      {configuring && (
        <div className="flex flex-col gap-2 border-t border-border/60 pt-5">
          {install.kind === "error" && <FormError>{install.message}</FormError>}
          {modelless.length > 0 && (
            <StatusIndicator kind="attention" size="sm" className="text-xs">
              Pick a model for: {modelless.map((a) => a.name).join(", ")}
            </StatusIndicator>
          )}
          {missing.length > 0 && (
            <StatusIndicator kind="attention" size="sm" className="text-xs">
              Fill required fields: {missing.map((f) => f.label).join(", ")}
            </StatusIndicator>
          )}
          <div className="flex items-center gap-2">
            <StartAgentButton
              size="xs"
              onClick={runInstall}
              isLoading={install.kind === "installing"}
              disabled={
                blocking.length > 0 ||
                missing.length > 0 ||
                modelless.length > 0
              }
            >
              {agentsKept ? t("start") : t("installBundle")}
            </StartAgentButton>
            <Button variant="ghost" size="sm" onClick={onCancel}>
              {tCommon("cancel")}
            </Button>
          </div>
        </div>
      )}

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

// ── Sections ────────────────────────────────────────────────────────────────

function BundleSections({
  preview,
  models,
  modelsError,
  edit,
  dispatch,
  canAdminister,
  onAddProvider,
  onRetryModels,
}: {
  preview: ImportPreview;
  models: ModelInstanceResponse[];
  modelsError: string | null;
  edit: BundleEdit;
  dispatch?: (action: BundleEditAction) => void;
  canAdminister: boolean;
  onAddProvider: () => void;
  onRetryModels: () => void;
}) {
  const tCommon = useTranslations("Common");
  const { agents, mcps, skills, automations, policies, channels, setup } =
    useMemo(
      () => ({
        agents: preview.bundle.agents ?? [],
        mcps: preview.bundle.mcps ?? [],
        skills: preview.bundle.skills ?? [],
        automations: preview.bundle.automations ?? [],
        policies: preview.bundle.policies ?? [],
        channels: preview.bundle.channels ?? [],
        setup: preview.setup ?? [],
      }),
      [preview]
    );
  const editing = dispatch !== undefined;

  const { byOwner, unbound } = useMemo(
    () => setupFieldPlacement(setup, mcps, channels, agents),
    [setup, mcps, channels, agents]
  );
  const installed = useMemo(
    () => installedMcpKeys(agents, edit),
    [agents, edit]
  );
  const nameOf = (items: { key: string; name: string }[], key: string) =>
    items.find((i) => i.key === key)?.name ?? key;
  const setupLabel = (key: string) =>
    setup.find((f) => f.key === key)?.label ?? key;

  const setupFields = (fields: SetupField[] | undefined) =>
    editing && fields && fields.length > 0 ? (
      <div className="grid gap-4 border-b border-border/60 px-[15px] py-[11px] md:grid-cols-2">
        {fields.map((f) => (
          <SetupFieldInput
            key={f.key}
            field={f}
            value={edit.setupValues[f.key]}
            onChange={(value) =>
              dispatch({ type: "setSetup", key: f.key, value })
            }
          />
        ))}
      </div>
    ) : null;

  return (
    <div className="space-y-4">
      {agents.length > 0 && (
        <SectionCard>
          <SectionCardHead
            icon={<ENTITY_ICONS.agent />}
            title={`Agents · ${agents.length}`}
          />
          {modelsError && (
            <div className="flex items-start gap-2 border-b border-border/60 px-[15px] py-[11px]">
              <FormError className="flex-1">{modelsError}</FormError>
              <Button size="xs" variant="outline" onClick={onRetryModels}>
                {tCommon("retry")}
              </Button>
            </div>
          )}
          {agents.map((agent) => (
            <AgentRow
              key={agent.key}
              agent={agent}
              preview={preview}
              models={models}
              edit={edit}
              dispatch={dispatch}
              canAdminister={canAdminister}
              mcpName={(key) => nameOf(mcps, key)}
              skillName={(key) => nameOf(skills, key)}
              onAddProvider={onAddProvider}
            />
          ))}
        </SectionCard>
      )}

      <div className="grid items-start gap-4 lg:grid-cols-2">
        {mcps.length > 0 && (
          <SectionCard>
            <SectionCardHead
              icon={<ENTITY_ICONS.mcp />}
              title={`Connections · ${mcps.length}`}
            />
            {mcps.map((m) => {
              const kept = !edit.mcpOff.has(m.key);
              const transport =
                typeof m.json_spec?.type === "string" ? m.json_spec.type : null;
              const needs = boundSetupKeys(m.bindings).map(setupLabel);
              return (
                <div key={m.key} className={cn(!kept && "opacity-60")}>
                  <FactRow
                    tile={<SoftTile icon={<ENTITY_ICONS.mcp />} />}
                    title={m.name}
                    sub={
                      [
                        transport,
                        needs.length > 0 ? `needs ${needs.join(", ")}` : null,
                        editing && kept && !installed.has(m.key)
                          ? "no agent uses it"
                          : null,
                      ]
                        .filter(Boolean)
                        .join(" · ") || null
                    }
                    trailing={
                      editing ? (
                        <Switch
                          checked={kept}
                          onCheckedChange={(on) =>
                            dispatch({
                              type: "toggleGlobalMcp",
                              key: m.key,
                              on,
                            })
                          }
                        />
                      ) : undefined
                    }
                  />
                  {kept && setupFields(byOwner[m.key])}
                </div>
              );
            })}
          </SectionCard>
        )}

        {skills.length > 0 && (
          <SectionCard>
            <SectionCardHead
              icon={<ENTITY_ICONS.skill />}
              title={`Skills · ${skills.length}`}
            />
            {skills.map((s) => (
              <FactRow
                key={s.key}
                tile={<SoftTile icon={<ENTITY_ICONS.skill />} />}
                title={s.name}
                sub={skillPreview(s.content)}
              />
            ))}
          </SectionCard>
        )}

        {automations.length > 0 && (
          <SectionCard>
            <SectionCardHead
              icon={<ENTITY_ICONS.trigger />}
              title={`Automations · ${automations.length}`}
            />
            {automations.map((a) => {
              const on = edit.autoEnabled[a.key] ?? false;
              const agentKept = !edit.agentOff.has(a.agent);
              return (
                <FactRow
                  key={a.key}
                  tile={<SoftTile icon={<ENTITY_ICONS.trigger />} />}
                  title={a.prompt || a.key}
                  sub={[
                    describeCronExpression(a.cron),
                    a.timezone,
                    nameOf(agents, a.agent),
                  ]
                    .filter(Boolean)
                    .join(" · ")}
                  trailing={
                    editing ? (
                      <Switch
                        checked={agentKept && on}
                        disabled={!agentKept}
                        onCheckedChange={(next) =>
                          dispatch({ type: "toggleAuto", key: a.key, on: next })
                        }
                      />
                    ) : (
                      <StatusIndicator kind={on ? "done" : "off"} size="sm">
                        {on ? "On" : "Off until enabled"}
                      </StatusIndicator>
                    )
                  }
                />
              );
            })}
          </SectionCard>
        )}

        {policies.length > 0 && (
          <SectionCard>
            <SectionCardHead
              icon={<ShieldCheck />}
              title={`Policies · ${policies.length}`}
            />
            {editing && !canAdminister && (
              <div className="border-b border-border/60 px-[15px] py-[11px]">
                <AdminOnlyHint action="importPolicies" />
              </div>
            )}
            {policies.map((p) => {
              const included = canAdminister && !edit.policyOff.has(p.key);
              const enabled = edit.policyEnabled[p.key] !== false;
              const rule = policyToRule(bundlePolicyAsPolicy(p, enabled));
              const Icon = EFFECT_STYLES[p.effect].icon;
              const subject =
                p.subject && p.subject !== "workspace"
                  ? nameOf(agents, p.subject)
                  : "Workspace";
              return (
                <FactRow
                  key={p.key}
                  tile={<SoftTile icon={<Icon />} />}
                  title={p.message || rule.label}
                  sub={[rule.category, rule.value, subject]
                    .filter(Boolean)
                    .join(" · ")}
                  trailing={
                    editing ? (
                      <span className="flex items-center gap-2">
                        <Checkbox
                          checked={included}
                          disabled={!canAdminister}
                          aria-label="Include policy"
                          onCheckedChange={(c) =>
                            dispatch({
                              type: "togglePolicyInclude",
                              key: p.key,
                              on: Boolean(c),
                            })
                          }
                        />
                        <Switch
                          checked={included && enabled}
                          disabled={!included}
                          onCheckedChange={(on) =>
                            dispatch({
                              type: "togglePolicyEnabled",
                              key: p.key,
                              on,
                            })
                          }
                        />
                      </span>
                    ) : undefined
                  }
                />
              );
            })}
          </SectionCard>
        )}

        {channels.length > 0 && (
          <SectionCard>
            <SectionCardHead
              icon={<Send />}
              title={`Channels · ${channels.length}`}
            />
            {channels.map((c) => {
              const on = edit.channelEnabled[c.key] ?? false;
              const agentKept = !edit.agentOff.has(c.agent);
              return (
                <div key={c.key}>
                  <FactRow
                    tile={<SoftTile icon={<Send />} />}
                    title={c.name}
                    sub={[c.type, nameOf(agents, c.agent)]
                      .filter(Boolean)
                      .join(" · ")}
                    trailing={
                      editing ? (
                        <Switch
                          checked={agentKept && on}
                          disabled={!agentKept}
                          onCheckedChange={(next) =>
                            dispatch({
                              type: "toggleChannel",
                              key: c.key,
                              on: next,
                            })
                          }
                        />
                      ) : (
                        <StatusIndicator kind={on ? "done" : "off"} size="sm">
                          {on ? "On" : "Off until enabled"}
                        </StatusIndicator>
                      )
                    }
                  />
                  {setupFields(byOwner[c.key])}
                </div>
              );
            })}
          </SectionCard>
        )}

        {unbound.length > 0 && (
          <SectionCard>
            <SectionCardHead icon={<SlidersHorizontal />} title="Settings" />
            {editing
              ? setupFields(unbound)
              : unbound.map((f) => (
                  <FactRow
                    key={f.key}
                    title={f.label}
                    sub={f.help}
                    trailing={
                      f.required ? (
                        <Badge variant="light" size="sm">
                          required
                        </Badge>
                      ) : undefined
                    }
                  />
                ))}
          </SectionCard>
        )}
      </div>
    </div>
  );
}

function AgentRow({
  agent,
  preview,
  models,
  edit,
  dispatch,
  canAdminister,
  mcpName,
  skillName,
  onAddProvider,
}: {
  agent: BundleAgent;
  preview: ImportPreview;
  models: ModelInstanceResponse[];
  edit: BundleEdit;
  dispatch?: (action: BundleEditAction) => void;
  canAdminister: boolean;
  mcpName: (key: string) => string;
  skillName: (key: string) => string;
  onAddProvider: () => void;
}) {
  const kept = !edit.agentOff.has(agent.key);
  const picked = edit.agentModels[agent.key] ?? null;
  const pickedModel = models.find((m) => m.id === picked);
  const suggestion = suggestedModel(agent, edit.setupValues);
  // The bundle's own model is worth a word only when it is not the one in use
  // here, e.g. "gpt-4o" from the workspace that published it.
  const showSuggestion =
    suggestion !== null &&
    suggestion !== picked &&
    !models.some((m) => m.id === suggestion);
  const toolScope = agentToolScope(preview, agent.key, canAdminister);

  return (
    <div
      className={cn(
        "space-y-3 border-b border-border/60 px-[15px] py-[13px] last:border-b-0",
        !kept && "opacity-60"
      )}
    >
      <div className="flex items-center gap-3">
        <AgentAvatar agent={{ id: agent.key, name: agent.name }} size="sm" />
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">
          {agent.name}
        </span>
        {dispatch && (
          <Switch
            checked={kept}
            aria-label={`Install ${agent.name}`}
            onCheckedChange={(on) =>
              dispatch({ type: "toggleAgent", key: agent.key, on })
            }
          />
        )}
      </div>
      {agent.instruction && (
        <p className="line-clamp-3 whitespace-pre-line text-xs text-muted-foreground">
          {agent.instruction}
        </p>
      )}

      <div className="grid gap-3 md:grid-cols-2">
        <div className="space-y-1.5">
          <Label className="text-xs text-muted-foreground">Model</Label>
          {dispatch ? (
            <ProviderModelSelector
              modelInstances={models}
              value={picked ?? undefined}
              disabled={!kept}
              onValueChange={(modelId) =>
                dispatch({ type: "setAgentModel", key: agent.key, modelId })
              }
              placeholder="Select a model"
              onAddProvider={onAddProvider}
            />
          ) : (
            <p className="text-sm">
              {pickedModel
                ? pickedModel.model_display_name || pickedModel.model_name
                : "No model in this workspace yet"}
            </p>
          )}
          {showSuggestion && (
            <p className="text-[11px] text-muted-foreground">
              The bundle suggests {suggestion}; it runs on a model of this
              workspace.
            </p>
          )}
        </div>

        {(agent.mcps ?? []).length > 0 && (
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Connections</Label>
            {dispatch ? (
              <div className="space-y-1.5">
                {(agent.mcps ?? []).map((ref) => {
                  const globallyOff = edit.mcpOff.has(ref);
                  return (
                    <label
                      key={ref}
                      className="flex items-center gap-2 text-sm"
                    >
                      <Checkbox
                        checked={isAgentMcpOn(edit, agent.key, ref)}
                        disabled={!kept || globallyOff}
                        onCheckedChange={(c) =>
                          dispatch({
                            type: "toggleAgentMcp",
                            agentKey: agent.key,
                            mcpKey: ref,
                            on: Boolean(c),
                          })
                        }
                      />
                      <span className="min-w-0 flex-1 truncate">
                        {mcpName(ref)}
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
            ) : (
              <RefList
                icon={<ENTITY_ICONS.mcp />}
                names={(agent.mcps ?? []).map(mcpName)}
              />
            )}
          </div>
        )}

        {(agent.skills ?? []).length > 0 && (
          <div className="space-y-1.5">
            <Label className="text-xs text-muted-foreground">Skills</Label>
            <RefList
              icon={<ENTITY_ICONS.skill />}
              names={(agent.skills ?? []).map(skillName)}
            />
          </div>
        )}
      </div>

      {(toolScope.allowed.length > 0 || toolScope.denied.length > 0) && (
        <StatusIndicator kind="attention" size="sm" className="text-[11px]">
          {toolScope.allowed.length > 0
            ? `Tools locked to ${toolScope.allowed.join(", ")}; all others blocked`
            : `Blocked tools: ${toolScope.denied.join(", ")}`}
        </StatusIndicator>
      )}
    </div>
  );
}

function RefList({ icon, names }: { icon: React.ReactNode; names: string[] }) {
  return (
    <div className="flex flex-wrap gap-1.5">
      {names.map((name) => (
        <Badge
          key={name}
          variant="light"
          size="sm"
          className="gap-1 [&>svg]:h-3 [&>svg]:w-3"
        >
          {icon}
          {name}
        </Badge>
      ))}
    </div>
  );
}

// Tool scoping is governance policy: allow/deny on `tool:X` bound to an agent.
function agentToolScope(
  preview: ImportPreview,
  agentKey: string,
  canAdminister: boolean
): { allowed: string[]; denied: string[] } {
  const allowed: string[] = [];
  const denied: string[] = [];
  if (!canAdminister) return { allowed, denied };
  for (const p of preview.bundle.policies ?? []) {
    if (p.subject !== agentKey) continue;
    const m = (p.target ?? "").match(/^tool:(.+)$/);
    if (!m || m[1] === "*") continue;
    if (p.effect === "allow") allowed.push(m[1]);
    else if (p.effect === "deny") denied.push(m[1]);
  }
  return { allowed, denied };
}

// First meaningful line of a SKILL.md body, without the "# Heading" that only
// repeats the skill name.
function skillPreview(content: string | null | undefined): string | null {
  if (!content) return null;
  return (
    content
      .split("\n")
      .map((l) => l.trim())
      .find((l) => l.length > 0 && !l.startsWith("#")) ?? null
  );
}

function SetupFieldInput({
  field,
  value,
  onChange,
}: {
  field: SetupField;
  value: unknown;
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
      {type === "boolean" ? (
        <div className="flex items-center gap-2">
          <Switch
            id={id}
            checked={Boolean(value)}
            onCheckedChange={(c) => onChange(c)}
          />
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
          type={
            type === "secret"
              ? "password"
              : type === "number"
                ? "number"
                : "text"
          }
          value={value === undefined || value === null ? "" : String(value)}
          placeholder={field.help ?? ""}
          onChange={(e) =>
            onChange(
              type === "number"
                ? e.target.valueAsNumber || e.target.value
                : e.target.value
            )
          }
        />
      )}
      {field.help && type !== "boolean" && (
        <p className="text-[11px] text-muted-foreground">{field.help}</p>
      )}
    </div>
  );
}

function InstallSummary({
  result,
  onBack,
}: {
  result: InstallResult;
  onBack: () => void;
}) {
  const entities = result.entities ?? [];
  const created = entities.filter((e) => e.action === "created");
  const reused = entities.filter((e) => e.action === "reused");
  const skipped = entities.filter((e) => e.action === "skipped");

  return (
    <SectionCard>
      <SectionCardHead
        icon={<Puzzle />}
        title={`Installed ${result.bundle_name}`}
      />
      <div className="border-b border-border/60 px-[15px] py-[11px]">
        <StatusIndicator kind="done" size="sm" className="text-sm">
          {created.length} created
          {reused.length > 0 ? `, ${reused.length} reused` : ""}
          {skipped.length > 0 ? `, ${skipped.length} skipped` : ""}.
        </StatusIndicator>
      </div>
      {entities.map((e) => (
        <FactRow
          key={`${e.kind}-${e.key}`}
          title={e.name}
          sub={e.kind}
          trailing={
            <Badge
              variant={e.action === "created" ? "blue" : "light"}
              size="sm"
              className="capitalize"
            >
              {e.action}
            </Badge>
          }
        />
      ))}
      <div className="flex items-center gap-2 px-[15px] py-[11px]">
        <Button asChild size="sm">
          <Link href="/agents">Go to Agents</Link>
        </Button>
        <Button variant="ghost" size="sm" onClick={onBack}>
          Done
        </Button>
      </div>
    </SectionCard>
  );
}
