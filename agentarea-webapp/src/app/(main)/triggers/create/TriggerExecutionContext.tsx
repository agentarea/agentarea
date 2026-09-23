"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ChevronRight, FileText, X } from "lucide-react";
import type {
  AgentResponse,
  McpServerInstanceResponse,
} from "@/api/client/types.gen";
import { InfoPanelBody, InfoPanelShell } from "@/components/InfoPanel";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { EntityIcon, type EntityKind } from "@/lib/entity-icons";
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
  mcpControl: ReactNode;
  skillControl: ReactNode;
  fileControl: ReactNode;
  onRemoveMcp: (id: string) => void;
  onRemoveSkill: (id: string) => void;
  onRemoveFile: (path: string) => void;
};

function ResourceGroup({
  title,
  control,
  children,
}: {
  title: string;
  control?: ReactNode;
  children: ReactNode;
}) {
  return (
    <section className="space-y-1">
      <div className="flex min-h-8 items-center justify-between gap-3">
        <h3 className="text-xs font-medium text-muted-foreground">{title}</h3>
        {control}
      </div>
      {children}
    </section>
  );
}

function ResourceRow({
  name,
  kind,
  origin,
  unavailable,
  href,
  children,
  remove,
}: {
  name: string;
  kind: EntityKind | "file";
  origin?: string;
  unavailable?: string;
  href?: string;
  children?: ReactNode;
  remove?: { label: string; onClick: () => void };
}) {
  return (
    <div className="flex items-start gap-2 py-1.5">
      <span className="mt-0.5 shrink-0 text-muted-foreground">
        {kind === "file" ? (
          <FileText className="h-4 w-4" />
        ) : (
          <EntityIcon kind={kind} />
        )}
      </span>
      <div className="min-w-0 flex-1">
        {href ? (
          <Link
            href={href}
            target="_blank"
            rel="noopener noreferrer"
            className="block break-words text-inputSize font-medium hover:underline"
          >
            {name}
          </Link>
        ) : (
          <p className="break-words text-inputSize font-medium">{name}</p>
        )}
        {(origin || unavailable) && (
          <div className="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-0.5 text-xs text-muted-foreground">
            {origin && <span>{origin}</span>}
            {unavailable && (
              <span className="text-destructive">{unavailable}</span>
            )}
          </div>
        )}
        {children}
      </div>
      {remove && (
        <Button
          type="button"
          variant="ghost"
          size="icon"
          className="-mt-1 h-8 w-8 shrink-0 text-muted-foreground"
          aria-label={remove.label}
          title={remove.label}
          onClick={remove.onClick}
        >
          <X />
        </Button>
      )}
    </div>
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
    <p className="py-1 text-xs text-muted-foreground">{t(key)}</p>
  );

  return (
    <aside aria-label={t("execution.title")} className="min-w-0">
      <InfoPanelShell className="h-auto overflow-visible border-l-0 lg:border-l">
        <InfoPanelBody>
          <div className="space-y-3 border-b border-border pb-4">
            <h2 className="text-sm font-semibold">{t("execution.title")}</h2>
            <div className="space-y-2">
              <div className="flex items-center justify-between gap-2">
                <h3 className="text-xs font-medium text-muted-foreground">
                  {t("execution.orchestrator")}
                </h3>
                {agent && (
                  <Link
                    href={`/agents/${agent.id}/settings`}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-muted-foreground hover:text-foreground hover:underline"
                  >
                    {t("execution.configureAgent")}
                  </Link>
                )}
              </div>
              {props.orchestratorControl}
            </div>
            {!props.selectedAgentId && empty("execution.selectAgent")}
            {pending && (
              <div
                role="status"
                className="flex items-center gap-2 text-xs text-muted-foreground"
              >
                <LoadingSpinner size="sm" />
                {t("execution.loading")}
              </div>
            )}
            {current?.error && (
              <div
                role="alert"
                className="flex items-center justify-between gap-2 text-xs text-destructive"
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
              <div role="alert" className="space-y-1 text-xs text-destructive">
                <p>{t("resourcesLoadFailed")}</p>
                <p>{resourceErrorLabels.join(", ")}</p>
              </div>
            )}
          </div>

          {agent && (
            <ResourceGroup title={t("execution.agents")}>
              {resources.delegatedAgents.length === 0 &&
                empty("execution.noAgents")}
              {resources.delegatedAgents.map((resource) => (
                <ResourceRow
                  key={resource.id}
                  kind="agent"
                  name={resource.name}
                  origin={
                    resource.remote ? t("execution.remoteAgent") : undefined
                  }
                  unavailable={
                    !props.resourcesLoading && resource.unavailable
                      ? t("execution.unavailable")
                      : undefined
                  }
                  href={
                    !resource.unavailable && !resource.remote
                      ? `/agents/${resource.id}`
                      : undefined
                  }
                >
                  {resource.approval && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t("execution.approval")}
                    </p>
                  )}
                </ResourceRow>
              ))}
            </ResourceGroup>
          )}

          <ResourceGroup title={t("execution.mcps")} control={props.mcpControl}>
            {!pending &&
              !current?.error &&
              !props.resourceErrors.includes("mcps") &&
              resources.mcps.length === 0 &&
              empty("execution.noMcps")}
            {resources.mcps.map((resource) => (
              <ResourceRow
                key={resource.id}
                kind="mcp"
                name={resource.name}
                origin={origin(resource)}
                unavailable={
                  !props.resourcesLoading && resource.unavailable
                    ? t("execution.unavailable")
                    : undefined
                }
                href={
                  !resource.unavailable
                    ? `/connections/${resource.id}`
                    : undefined
                }
                remove={remove(resource, props.onRemoveMcp)}
              >
                {agent &&
                  !pending &&
                  !current?.error &&
                  !resource.unavailable && (
                    <details className="group mt-1.5 text-xs text-muted-foreground">
                      <summary className="flex w-fit cursor-pointer list-none items-center gap-1 rounded-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
                        <ChevronRight className="h-3 w-3 transition-transform group-open:rotate-90 motion-reduce:transition-none" />
                        {resource.restricted
                          ? t("execution.selectedTools", {
                              count: resource.tools.length,
                            })
                          : t("execution.allTools")}
                      </summary>
                      <div className="mt-2 space-y-2 border-l border-border pl-3">
                        {resource.tools.length === 0 && (
                          <p>{t("execution.toolListUnavailable")}</p>
                        )}
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
                {resource.settings?.requires_user_confirmation && (
                  <p className="mt-1 text-xs text-muted-foreground">
                    {t("execution.approval")}
                  </p>
                )}
              </ResourceRow>
            ))}
          </ResourceGroup>

          <ResourceGroup
            title={t("execution.skills")}
            control={props.skillControl}
          >
            {!pending &&
              !current?.error &&
              !props.resourceErrors.includes("skills") &&
              resources.skills.length === 0 &&
              empty("execution.noSkills")}
            {resources.skills.map((resource) => (
              <ResourceRow
                key={resource.id}
                kind="skill"
                name={resource.name}
                origin={origin(resource)}
                unavailable={
                  !props.resourcesLoading && resource.unavailable
                    ? t("execution.unavailable")
                    : undefined
                }
                href={
                  !resource.unavailable ? `/skills/${resource.id}` : undefined
                }
                remove={remove(resource, props.onRemoveSkill)}
              />
            ))}
          </ResourceGroup>

          <ResourceGroup
            title={t("execution.files")}
            control={props.fileControl}
          >
            {props.selectedFiles.length === 0 && empty("execution.noFiles")}
            {props.selectedFiles.map((path) => (
              <ResourceRow
                key={path}
                kind="file"
                name={path}
                origin={t("execution.thisTask")}
                remove={{
                  label: t("execution.remove", { name: path }),
                  onClick: () => props.onRemoveFile(path),
                }}
              />
            ))}
          </ResourceGroup>

          {resources.capabilities.length > 0 && (
            <ResourceGroup title={t("execution.capabilities")}>
              {resources.capabilities.map((tool) => (
                <ResourceRow
                  key={tool.id}
                  kind="tool"
                  name={tool.name}
                  origin={
                    tool.type === "openapi" ? "OpenAPI" : t("execution.builtin")
                  }
                >
                  {tool.approval && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {t("execution.approval")}
                    </p>
                  )}
                  {tool.allowedTools.length > 0 && (
                    <p className="mt-1 break-words text-xs text-muted-foreground">
                      {tool.allowedTools.join(", ")}
                    </p>
                  )}
                  {tool.disabledMethods.length > 0 && (
                    <p className="mt-1 break-words text-xs text-muted-foreground">
                      {t("execution.disabledMethods")}:{" "}
                      {tool.disabledMethods.join(", ")}
                    </p>
                  )}
                </ResourceRow>
              ))}
            </ResourceGroup>
          )}
        </InfoPanelBody>
      </InfoPanelShell>
    </aside>
  );
}
