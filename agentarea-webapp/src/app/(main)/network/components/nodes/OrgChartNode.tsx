"use client";

import { useTranslations } from "next-intl";
import { Handle, Position, type Node, type NodeProps } from "@xyflow/react";
import { Globe, HelpCircle, LockKeyhole } from "lucide-react";
import { EntityIcon, type EntityKind } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";
import type { NetworkFlowNodeData } from "../../types";
import { getNetworkScope } from "../../utils/networkConnections";

const kinds: Record<NetworkFlowNodeData["type"], EntityKind> = {
  agent: "agent",
  mcp_instance: "mcp",
  openapi_connection: "client",
  skill: "skill",
  trigger: "trigger",
};

export default function OrgChartNode({
  data,
}: NodeProps<Node<NetworkFlowNodeData>>) {
  const t = useTranslations("NetworkPage.orgChart");
  const scopeText = useTranslations("NetworkPage.accessDetails");
  const scope = getNetworkScope(data);
  const status = data.status?.toLowerCase();
  const active =
    status &&
    ["active", "running", "enabled", "connected", "available"].includes(status);
  const failed = status && ["error", "failed", "unhealthy"].includes(status);
  return (
    <div
      title={data.label}
      className={cn(
        "h-[104px] w-[240px] rounded-lg border border-border bg-background shadow-sm transition-[opacity,box-shadow,border-color] motion-reduce:transition-none",
        "hover:border-primary/50 hover:shadow-md",
        data._dimmed && "opacity-30",
        data._highlighted && "border-primary ring-2 ring-primary/20"
      )}
    >
      <Handle
        type="target"
        position={data._horizontal ? Position.Left : Position.Top}
        isConnectable={false}
        className="!h-1.5 !w-1.5 !border-background !bg-zinc-400 dark:!bg-zinc-500"
      />
      <div className="flex items-start gap-3 px-4 pt-3.5">
        <div
          className={cn(
            "flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground",
            data.type === "agent" && "bg-primary/10 text-primary",
            data.type === "trigger" &&
              "bg-amber-50 text-amber-700 dark:bg-amber-950/50 dark:text-amber-300",
            (data.type === "mcp_instance" ||
              data.type === "openapi_connection") &&
              "bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300"
          )}
        >
          <EntityIcon kind={kinds[data.type]} />
        </div>
        <p className="line-clamp-2 min-h-10 min-w-0 break-words text-sm font-semibold leading-5 text-foreground">
          {data.label}
        </p>
      </div>
      <div className="mx-4 mt-2 flex items-center justify-between gap-2 border-t border-border/70 pt-2 text-[11px] leading-4 text-muted-foreground">
        <span className="flex min-w-0 items-center gap-1.5">
          <span className="truncate">{t(`types.${data.type}`)}</span>
          {data._horizontal &&
          data.type !== "agent" &&
          data.type !== "trigger" ? (
            <span
              title={scopeText(`scopeDescription.${scope}`)}
              aria-label={scopeText(`scope.${scope}`)}
            >
              {scope === "egress" ? (
                <Globe className="h-3 w-3 text-amber-600 dark:text-amber-400" />
              ) : scope === "private" ? (
                <LockKeyhole className="h-3 w-3" />
              ) : (
                <HelpCircle className="h-3 w-3" />
              )}
            </span>
          ) : null}
        </span>
        {status && (
          <span
            className="flex min-w-0 items-center gap-1.5"
            title={data.status ?? undefined}
          >
            <span
              className={cn(
                "h-1.5 w-1.5 shrink-0 rounded-full bg-zinc-400",
                active && "bg-emerald-500",
                failed && "bg-red-500"
              )}
            />
            <span className="truncate">
              {t.has(`statuses.${status}`)
                ? t(`statuses.${status}`)
                : data.status}
            </span>
          </span>
        )}
      </div>
      <Handle
        type="source"
        position={data._horizontal ? Position.Right : Position.Bottom}
        isConnectable={false}
        className="!h-1.5 !w-1.5 !border-background !bg-zinc-400 dark:!bg-zinc-500"
      />
    </div>
  );
}
