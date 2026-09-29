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
import { Globe, HelpCircle, LockKeyhole, Users } from "lucide-react";
import EntityMark from "@/components/EntityMark";
import { cn } from "@/lib/utils";
import type { NetworkFlowNodeData } from "../../types";
import { getNetworkScope, getNodeIdentity } from "../../utils/networkConnections";
import { RESOURCE_TILE } from "../../utils/networkMapLayout";

/**
 * Everything an agent reaches — MCP servers, OpenAPI connections, skills,
 * triggers — as one square tile. A logo is recognisable at a glance where a
 * name is not, so the tile leads with the service's own mark and lets the
 * label follow; the type name and status live in the tooltip, which keeps a
 * lane of twenty connections readable instead of a wall of cards.
 */
export default function ResourceNode({
  id,
  data,
}: NodeProps<Node<NetworkFlowNodeData>>) {
  const updateNodeInternals = useUpdateNodeInternals();
  useLayoutEffect(() => {
    updateNodeInternals(id);
  }, [id, data._horizontal, data._targetTop, updateNodeInternals]);
  const t = useTranslations("NetworkPage.orgChart");
  const networkText = useTranslations("NetworkPage.networkMap");
  const scopeText = useTranslations("NetworkPage.accessDetails");
  const scope = getNetworkScope(data);
  const status = data.status?.toLowerCase();
  const active =
    status &&
    ["active", "running", "enabled", "connected", "available"].includes(status);
  const failed = status && ["error", "failed", "unhealthy"].includes(status);
  const statusLabel = status
    ? t.has(`statuses.${status}`)
      ? t(`statuses.${status}`)
      : data.status
    : null;
  const showScope = data.type !== "trigger";

  return (
    <div
      title={[data.label, t(`types.${data.type}`), statusLabel]
        .filter(Boolean)
        .join(" — ")}
      style={{ width: RESOURCE_TILE, height: RESOURCE_TILE }}
      className={cn(
        "flex flex-col items-center rounded-lg border border-border bg-background px-2 pb-1.5 pt-3 shadow-sm transition-[opacity,box-shadow,border-color] motion-reduce:transition-none",
        "hover:border-primary/50 hover:shadow-md",
        data._dimmed && "opacity-30",
        data._highlighted && "border-primary ring-2 ring-primary/20"
      )}
    >
      <Handle
        type="target"
        position={
          data._targetTop
            ? Position.Top
            : data._horizontal
              ? Position.Left
              : Position.Top
        }
        isConnectable={false}
        className="!h-1.5 !w-1.5 !border-background !bg-zinc-400 dark:!bg-zinc-500"
      />

      <div className="relative">
        <span className="flex h-9 w-9 items-center justify-center overflow-hidden rounded-md bg-muted text-muted-foreground">
          <EntityMark
            identity={getNodeIdentity(data)}
            className="h-5 w-5 rounded-[3px]"
          />
        </span>
        {status && (
          <span
            className={cn(
              "absolute -right-0.5 -top-0.5 h-2 w-2 rounded-full border-2 border-background bg-zinc-400",
              active && "bg-emerald-500",
              failed && "bg-red-500"
            )}
          />
        )}
      </div>

      <p className="mt-1.5 line-clamp-2 w-full break-words text-center text-[10px] font-medium leading-[1.25] text-foreground">
        {data.label}
      </p>

      <div className="mt-auto flex w-full items-center justify-between text-muted-foreground">
        {showScope ? (
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
        ) : (
          <span />
        )}
        {typeof data._sharedBy === "number" && data._sharedBy > 1 && (
          <span
            className="flex items-center gap-0.5 text-[9px]"
            title={networkText("sharedBy", { count: data._sharedBy })}
            aria-label={networkText("sharedBy", { count: data._sharedBy })}
          >
            <Users className="h-3 w-3" />
            <span className="tabular-nums">{data._sharedBy}</span>
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
