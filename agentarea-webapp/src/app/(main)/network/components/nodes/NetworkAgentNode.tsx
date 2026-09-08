"use client";

import { useLayoutEffect } from "react";
import { useTranslations } from "next-intl";
import {
  Handle,
  Position,
  useUpdateNodeInternals,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import {
  ChevronDown,
  ChevronUp,
  Globe,
  HelpCircle,
  LockKeyhole,
  ShieldCheck,
  Users,
} from "lucide-react";
import { EntityIcon, type EntityKind } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";
import type { NetworkFlowNodeData, NetworkNodeData } from "../../types";
import { getNetworkScope } from "../../utils/networkConnections";
import { NETWORK_RESOURCE_LIMIT } from "../../utils/networkMapLayout";

export interface NetworkAgentData extends NetworkFlowNodeData {
  resources: { node: NetworkNodeData; sharedBy: number }[];
  expanded: boolean;
  showResources?: boolean;
  horizontal?: boolean;
  clustered?: boolean;
  selectedResourceId?: string | null;
  onResourceClick: (node: NetworkNodeData) => void;
  onToggleResources: () => void;
  onInspect: () => void;
}

const resourceKinds: Record<NetworkNodeData["type"], EntityKind> = {
  agent: "agent",
  mcp_instance: "mcp",
  openapi_connection: "client",
  skill: "skill",
  trigger: "trigger",
};

export default function NetworkAgentNode({
  id,
  data,
}: NodeProps<Node<NetworkAgentData>>) {
  const updateNodeInternals = useUpdateNodeInternals();
  useLayoutEffect(() => {
    updateNodeInternals(id);
  }, [id, data.clustered, data.horizontal, updateNodeInternals]);
  const t = useTranslations("NetworkPage.networkMap");
  const accessText = useTranslations("NetworkPage.accessDetails");
  const common = useTranslations("NetworkPage.orgChart");
  const status = data.status?.toLowerCase();
  const active =
    status &&
    ["active", "running", "enabled", "connected", "available"].includes(status);
  const failed = status && ["error", "failed", "unhealthy"].includes(status);
  const resources = data.expanded
    ? data.resources
    : data.resources.slice(0, NETWORK_RESOURCE_LIMIT);
  const model = data.metadata.model_info;
  const modelName =
    model &&
    typeof model === "object" &&
    "model_display_name" in model &&
    typeof model.model_display_name === "string"
      ? model.model_display_name
      : null;

  return (
    <div
      className={cn(
        "h-full w-72 rounded-lg border border-border bg-background shadow-sm transition-[opacity,box-shadow,border-color] motion-reduce:transition-none hover:border-primary/50 hover:shadow-md",
        data._dimmed && "opacity-30",
        data._highlighted && "border-primary ring-2 ring-primary/20"
      )}
    >
      <Handle
        type="target"
        id={data.clustered ? "flow-target" : undefined}
        position={data.horizontal === false ? Position.Top : Position.Left}
        isConnectable={false}
        className="!h-1.5 !w-1.5 !border-background !bg-zinc-400 dark:!bg-zinc-500"
      />
      <div className="h-[102px] px-4 pt-4">
        <div className="flex items-start gap-3">
          <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
            <EntityIcon kind="agent" />
          </div>
          <div className="min-w-0 flex-1">
            <p
              className="line-clamp-2 min-h-10 break-words text-sm font-semibold leading-5 text-foreground"
              title={data.label}
            >
              {data.label}
            </p>
          </div>
        </div>
        <div className="mt-3 flex min-w-0 items-center justify-between gap-2 text-[11px] text-muted-foreground">
          <span className="truncate" title={modelName ?? undefined}>
            {data.clustered
              ? t("resourceCount", {
                  count: data.resources.filter(
                    (resource) => resource.node.type !== "trigger"
                  ).length,
                })
              : (modelName ?? common("types.agent"))}
          </span>
          <button
            type="button"
            onClick={(event) => {
              event.stopPropagation();
              data.onInspect();
            }}
            onKeyDown={(event) => event.stopPropagation()}
            className="nodrag nopan ml-auto inline-flex items-center gap-1 rounded px-1 py-0.5 text-primary hover:bg-primary/10 focus-visible:ring-2 focus-visible:ring-primary"
            aria-label={accessText("inspectAgent", { name: data.label })}
            title={accessText("policyTitle")}
          >
            <ShieldCheck className="h-3 w-3" />
            <span>{accessText("permissions")}</span>
          </button>
          {status && (
            <span className="flex min-w-0 shrink-0 items-center gap-1.5">
              <span
                className={cn(
                  "h-1.5 w-1.5 rounded-full bg-zinc-400",
                  active && "bg-emerald-500",
                  failed && "bg-red-500"
                )}
              />
              <span>
                {common.has(`statuses.${status}`)
                  ? common(`statuses.${status}`)
                  : data.status}
              </span>
            </span>
          )}
        </div>
      </div>
      {data.showResources !== false && (
        <div className="border-t border-border bg-muted/25">
          {data.resources.length === 0 ? (
            <p className="flex h-9 items-center px-4 text-[11px] text-muted-foreground">
              {t("noResources")}
            </p>
          ) : (
            <>
              <div className="flex h-9 items-center justify-between px-4 text-[11px] text-muted-foreground">
                <span>{t("resources")}</span>
                <span className="tabular-nums">{data.resources.length}</span>
              </div>
              <div className="px-2">
                {resources.map(({ node, sharedBy }) => (
                  <button
                    key={node.id}
                    type="button"
                    className={cn(
                      "nodrag nopan flex h-7 w-full items-center gap-2 rounded px-2 text-left text-[11px] text-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary",
                      data.selectedResourceId === node.id &&
                        "bg-primary/10 text-primary"
                    )}
                    onClick={(event) => {
                      event.stopPropagation();
                      data.onResourceClick(node);
                    }}
                    onKeyDown={(event) => event.stopPropagation()}
                    title={`${node.label} — ${common(`types.${node.type}`)}`}
                  >
                    <EntityIcon
                      kind={resourceKinds[node.type]}
                      className={cn(
                        "h-3.5 w-3.5 shrink-0 text-muted-foreground",
                        node.type === "trigger" &&
                          "text-amber-600 dark:text-amber-400",
                        (node.type === "mcp_instance" ||
                          node.type === "openapi_connection") &&
                          "text-emerald-600 dark:text-emerald-400"
                      )}
                    />
                    <span className="min-w-0 flex-1 truncate">
                      {node.label}
                    </span>
                    {node.type !== "trigger" && (
                      <span
                        className="shrink-0 text-muted-foreground"
                        title={accessText(
                          `scopeDescription.${getNetworkScope(node)}`
                        )}
                        aria-label={accessText(
                          `scope.${getNetworkScope(node)}`
                        )}
                      >
                        {getNetworkScope(node) === "egress" ? (
                          <Globe className="h-3 w-3 text-amber-600 dark:text-amber-400" />
                        ) : getNetworkScope(node) === "private" ? (
                          <LockKeyhole className="h-3 w-3" />
                        ) : (
                          <HelpCircle className="h-3 w-3" />
                        )}
                      </span>
                    )}
                    {sharedBy > 1 && (
                      <span
                        className="flex items-center gap-1 text-muted-foreground"
                        title={t("sharedBy", { count: sharedBy })}
                        aria-label={t("sharedBy", { count: sharedBy })}
                      >
                        <Users className="h-3 w-3" />
                        <span className="tabular-nums">{sharedBy}</span>
                      </span>
                    )}
                  </button>
                ))}
              </div>
              {data.resources.length > NETWORK_RESOURCE_LIMIT && (
                <button
                  type="button"
                  className="nodrag nopan flex h-8 w-full items-center justify-between px-4 text-[11px] text-primary hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
                  aria-expanded={data.expanded}
                  onClick={(event) => {
                    event.stopPropagation();
                    data.onToggleResources();
                  }}
                  onKeyDown={(event) => event.stopPropagation()}
                >
                  <span>
                    {data.expanded
                      ? t("collapse")
                      : t("more", {
                          count: data.resources.length - NETWORK_RESOURCE_LIMIT,
                        })}
                  </span>
                  {data.expanded ? (
                    <ChevronUp className="h-3 w-3" />
                  ) : (
                    <ChevronDown className="h-3 w-3" />
                  )}
                </button>
              )}
            </>
          )}
        </div>
      )}
      {data.clustered && (
        <>
          <Handle
            id="delegation-target"
            type="target"
            position={Position.Top}
            isConnectable={false}
            className="!h-1.5 !w-1.5 !border-background !bg-zinc-400 dark:!bg-zinc-500"
          />
          <Handle
            id="delegation-source"
            type="source"
            position={Position.Bottom}
            isConnectable={false}
            className="!h-1.5 !w-1.5 !border-background !bg-zinc-400 dark:!bg-zinc-500"
          />
        </>
      )}
      <Handle
        type="source"
        id={data.clustered ? "flow-source" : undefined}
        position={data.horizontal === false ? Position.Bottom : Position.Right}
        isConnectable={false}
        className="!h-1.5 !w-1.5 !border-background !bg-zinc-400 dark:!bg-zinc-500"
      />
    </div>
  );
}
