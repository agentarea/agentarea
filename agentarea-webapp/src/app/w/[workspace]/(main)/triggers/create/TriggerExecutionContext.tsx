"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowUpRight, ChevronRight, FileText, Network, X } from "lucide-react";
import type {
  AgentResponse,
  McpServerInstanceResponse,
} from "@/api/client/types.gen";
import { AgentAvatar } from "@/components/AgentAvatar";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  InfoPanelBody,
  InfoPanelHeader,
  InfoPanelRow,
  InfoPanelSection,
  InfoPanelShell,
} from "@/components/InfoPanel";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import ActionLink from "@/components/TaskInfoPanel/components/ActionLink";
import { Button } from "@/components/ui/button";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import Link from "@/components/WorkspaceLink";
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS, type EntityKind } from "@/lib/entity-icons";
import { getAgentAction } from "@/lib/server-actions";
import type { TaskParameterRef } from "../components/taskParameters";
import {
  buildExecutionResources,
  type ExecutionResource,
} from "./executionResources";

type TriggerExecutionContextProps = {
  selectedAgentId: string;
  agents: AgentResponse[];
  availableMcps: McpServerInstanceResponse[];
  availableSkills: TaskParameterRef[];
  selectedMcps: TaskParameterRef[];
  selectedSkills: TaskParameterRef[];
  selectedFiles: string[];
  resourcesLoading: boolean;
  resourceErrors: string[];
  refreshKey: number;
  orchestratorControl: ReactNode;
  fileControl: ReactNode;
  onRemoveMcp: (id: string) => void;
  onRemoveSkill: (id: string) => void;
  onRemoveFile: (path: string) => void;
};

/** An entity's tile as the house draws it: graphite, hued by its id. */
function tile(kind: EntityKind, id: string) {
  const Icon = ENTITY_ICONS[kind];
  return (
    <EntityAvatar
      size={20}
      hue={deterministicHue(id)}
      icon={<Icon strokeWidth={1.85} />}
      aria-hidden
    />
  );
}

/** The muted line under a row: its facts, then "unavailable" in red. */
function subLine(parts: unknown[], unavailable?: string | false) {
  const facts = parts.filter(
    (part): part is string => typeof part === "string" && part.length > 0
  );
  if (!facts.length && !unavailable) return undefined;
  return (
    <>
      {facts.join(" · ")}
      {unavailable && (
        <span className="text-destructive">
          {facts.length ? " · " : ""}
          {unavailable}
        </span>
      )}
    </>
  );
}

function removeButton(remove?: { label: string; onClick: () => void }) {
  if (!remove) return undefined;
  return (
    <Button
      type="button"
      variant="ghost"
      size="icon"
      className="h-6 w-6 shrink-0 text-muted-foreground"
      aria-label={remove.label}
      title={remove.label}
      onClick={remove.onClick}
    >
      <X className="h-3.5 w-3.5" />
    </Button>
  );
}

function SectionLink({
  href,
  children,
}: {
  href: string;
  children: ReactNode;
}) {
  return (
    <Link
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="text-[11px] normal-case text-muted-foreground transition-colors hover:text-foreground"
    >
      {children}
    </Link>
  );
}

export function TriggerExecutionContext(props: TriggerExecutionContextProps) {
  const t = useTranslations("TriggersPage.create");
  const [attempt, setAttempt] = useState(0);
  const [loaded, setLoaded] = useState<{
    key: string;
    agent: AgentResponse | null;
    error: boolean;
  } | null>(null);
  const requestKey = `${props.selectedAgentId}:${props.refreshKey}:${attempt}`;
  const current = loaded?.key === requestKey ? loaded : null;
  const agentPending = Boolean(props.selectedAgentId) && !current;
  const agent = current?.agent ?? null;

  useEffect(() => {
    if (!props.selectedAgentId) return;
    let active = true;
    getAgentAction(props.selectedAgentId)
      .then((result) => {
        if (active)
          setLoaded({
            key: requestKey,
            agent: result.data ?? null,
            error: Boolean(result.error || !result.data),
          });
      })
      .catch(() => {
        if (active) setLoaded({ key: requestKey, agent: null, error: true });
      });
    return () => {
      active = false;
    };
  }, [props.selectedAgentId, requestKey]);

  const resources = buildExecutionResources({ ...props, agent });
  const pending = agentPending || props.resourcesLoading;
  const resourceErrorLabels = props.resourceErrors.flatMap((key) => {
    if (key === "mcps" || key === "skills" || key === "files")
      return [t(`execution.${key}`)];
    return [];
  });
  const origin = (resource: ExecutionResource) =>
    resource.inherited && resource.taskRefIds.length === 0
      ? undefined
      : t(
          resource.inherited
            ? resource.taskRefIds.length
              ? "execution.inheritedAndTask"
              : "execution.fromAgent"
            : "execution.thisTask"
        );
  const remove = (
    resource: ExecutionResource,
    callback: (id: string) => void
  ) =>
    resource.taskRefIds.length
      ? {
          label: t("execution.remove", { name: resource.name }),
          onClick: () => resource.taskRefIds.forEach(callback),
        }
      : undefined;
  const empty = (key: string) => (
    <p className="py-1 text-[11px] text-muted-foreground">{t(key)}</p>
  );
  // Triggers used to carry their own MCP servers and skills. They no longer
  // can, but ones saved back then still do, and an edit must not quietly drop
  // them — so they stay listed, removable, and labelled as the leftovers they
  // are rather than looking like something this form still offers.
  const carriedOver = [...resources.mcps, ...resources.skills].some(
    (resource) => resource.taskRefIds.length > 0
  );

  return (
    <aside aria-label={t("execution.title")} className="min-w-0 lg:h-full">
      <InfoPanelShell className="h-auto overflow-visible border-l-0 border-t lg:h-full lg:overflow-auto lg:border-l lg:border-t-0">
        <InfoPanelHeader label={t("execution.title")} className="px-3.5" />
        <InfoPanelBody className="space-y-1.5 pt-0">
          <div className="space-y-2 pb-2 text-xs">
            <div className="flex items-center justify-between gap-2">
              <FormLabel htmlFor="agent_id" icon={ENTITY_ICONS.agent} required>
                {t("execution.orchestrator")}
              </FormLabel>
              {agent && (
                <SectionLink href={`/agents/${agent.id}/settings`}>
                  {t("execution.configureAgent")}
                </SectionLink>
              )}
            </div>
            {props.orchestratorControl}
            {!props.selectedAgentId && empty("execution.selectAgent")}
            {pending && (
              <div
                role="status"
                className="flex items-center gap-2 text-[11px] text-muted-foreground"
              >
                <LoadingSpinner size="sm" />
                {t("execution.loading")}
              </div>
            )}
            {current?.error && (
              <div
                role="alert"
                className="flex items-center justify-between gap-2 text-[11px] text-destructive"
              >
                <span>{t("execution.agentError")}</span>
                <Button
                  type="button"
                  variant="ghost"
                  size="xs"
                  onClick={() => setAttempt((value) => value + 1)}
                >
                  {t("execution.retry")}
                </Button>
              </div>
            )}
            {resourceErrorLabels.length > 0 && (
              <p role="alert" className="text-[11px] text-destructive">
                {t("resourcesLoadFailed")} {resourceErrorLabels.join(", ")}
              </p>
            )}
          </div>

          {agent && (
            <InfoPanelSection
              title={t("execution.agents")}
              contentClassName="space-y-0.5 text-xs"
            >
              {resources.delegatedAgents.length === 0 &&
                empty("execution.noAgents")}
              {resources.delegatedAgents.map((resource) => (
                <InfoPanelRow
                  key={resource.id}
                  avatar={
                    <AgentAvatar
                      agent={{ id: resource.id, name: resource.name }}
                      size="xs"
                    />
                  }
                  name={resource.name}
                  sub={subLine(
                    [
                      resource.remote && t("execution.remoteAgent"),
                      resource.approval && t("execution.approval"),
                    ],
                    !props.resourcesLoading &&
                      resource.unavailable &&
                      t("execution.unavailable")
                  )}
                  href={
                    !resource.unavailable && !resource.remote
                      ? `/agents/${resource.id}`
                      : undefined
                  }
                  newTab
                />
              ))}
            </InfoPanelSection>
          )}

          <InfoPanelSection
            title={t("execution.mcps")}
            contentClassName="space-y-0.5 text-xs"
          >
            {!pending &&
              !current?.error &&
              !props.resourceErrors.includes("mcps") &&
              resources.mcps.length === 0 &&
              empty("execution.noMcps")}
            {resources.mcps.map((resource) => (
              <InfoPanelRow
                key={resource.id}
                avatar={tile("mcp", resource.id)}
                name={resource.name}
                sub={subLine(
                  [
                    origin(resource),
                    resource.settings?.requires_user_confirmation &&
                      t("execution.approval"),
                    // Locked down to nothing: no list to unfold, but worth
                    // saying, since the agent cannot call this server at all.
                    resource.restricted &&
                      resource.tools.length === 0 &&
                      t("execution.noTools"),
                  ],
                  !props.resourcesLoading &&
                    resource.unavailable &&
                    t("execution.unavailable")
                )}
                href={
                  !resource.unavailable
                    ? `/connections/${resource.id}`
                    : undefined
                }
                newTab
                trailing={removeButton(remove(resource, props.onRemoveMcp))}
              >
                {agent &&
                  !pending &&
                  !current?.error &&
                  !resource.unavailable &&
                  // Nothing to unfold without a tool list.
                  resource.tools.length > 0 && (
                    <details className="group mb-1 ml-7 text-[11px] text-muted-foreground">
                      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 rounded-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                        <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90 motion-reduce:transition-none" />
                        {!resource.restricted
                          ? t("execution.allTools")
                          : t("execution.selectedTools", {
                              count: resource.tools.length,
                            })}
                      </summary>
                      <div className="mt-1.5 space-y-1.5 border-l border-border pl-3">
                        {resource.tools.map((tool) => (
                          <div key={tool.name} className="space-y-0.5">
                            <p className="break-words font-mono text-foreground">
                              {tool.name}
                            </p>
                            {tool.approval && <p>{t("execution.approval")}</p>}
                            {tool.unavailable && (
                              <p className="text-destructive">
                                {t("execution.unavailable")}
                              </p>
                            )}
                          </div>
                        ))}
                      </div>
                    </details>
                  )}
              </InfoPanelRow>
            ))}
          </InfoPanelSection>

          <InfoPanelSection
            title={t("execution.skills")}
            contentClassName="space-y-0.5 text-xs"
          >
            {!pending &&
              !current?.error &&
              !props.resourceErrors.includes("skills") &&
              resources.skills.length === 0 &&
              empty("execution.noSkills")}
            {resources.skills.map((resource) => (
              <InfoPanelRow
                key={resource.id}
                avatar={tile("skill", resource.id)}
                name={resource.name}
                sub={subLine(
                  [origin(resource)],
                  !props.resourcesLoading &&
                    resource.unavailable &&
                    t("execution.unavailable")
                )}
                href={
                  !resource.unavailable ? `/skills/${resource.id}` : undefined
                }
                newTab
                trailing={removeButton(remove(resource, props.onRemoveSkill))}
              />
            ))}
          </InfoPanelSection>

          <InfoPanelSection
            title={t("execution.files")}
            action={props.fileControl}
            contentClassName="space-y-0.5 text-xs"
          >
            {props.selectedFiles.length === 0 && empty("execution.noFiles")}
            {props.selectedFiles.map((path) => (
              <InfoPanelRow
                key={path}
                avatar={
                  <EntityAvatar
                    size={20}
                    variant="soft"
                    icon={<FileText strokeWidth={1.85} />}
                    aria-hidden
                  />
                }
                name={path}
                sub={t("execution.thisTask")}
                trailing={removeButton({
                  label: t("execution.remove", { name: path }),
                  onClick: () => props.onRemoveFile(path),
                })}
              />
            ))}
          </InfoPanelSection>

          {resources.capabilities.length > 0 && (
            <InfoPanelSection
              title={t("execution.capabilities")}
              contentClassName="space-y-0.5 text-xs"
            >
              {resources.capabilities.map((tool) => (
                <InfoPanelRow
                  key={tool.id}
                  avatar={tile("tool", tool.id)}
                  name={tool.name}
                  sub={subLine([
                    tool.type === "openapi"
                      ? "OpenAPI"
                      : t("execution.builtin"),
                    tool.approval && t("execution.approval"),
                    tool.type === "openapi" &&
                      (tool.allowedTools === null
                        ? t("execution.allTools")
                        : tool.allowedTools.length === 0
                          ? t("execution.noTools")
                          : tool.allowedTools.join(", ")),
                    tool.disabledMethods.length > 0 &&
                      `${t("execution.disabledMethods")}: ${tool.disabledMethods.join(", ")}`,
                  ])}
                />
              ))}
            </InfoPanelSection>
          )}

          {carriedOver && (
            <p className="rounded-md border border-border/60 bg-muted/40 px-2.5 py-2 text-[11px] text-muted-foreground">
              {t("execution.carriedOver")}
            </p>
          )}

          {props.selectedAgentId && (
            <ActionLink
              href={`/network?focus=agent:${props.selectedAgentId}`}
              newTab
              icon={
                <ArrowUpRight
                  strokeWidth={1.5}
                  className="h-3.5 w-3.5 text-muted-foreground"
                />
              }
              className="text-xs"
            >
              <span className="flex items-center gap-2">
                <Network className="h-3.5 w-3.5 text-muted-foreground" />
                {t("execution.viewInNetwork")}
              </span>
            </ActionLink>
          )}
        </InfoPanelBody>
      </InfoPanelShell>
    </aside>
  );
}
