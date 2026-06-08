"use client";

import Image from "next/image";
import { Activity, MoreHorizontal } from "lucide-react";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";
import type { Agent, ModelInfo } from "@/types/agent";
import { getToolAvatars } from "@/utils/toolsDisplay";

/* ---------------- status ---------------- */

export interface AgentStatusMeta {
  label: string;
  color: string;
}

const STATUS_META: Record<string, AgentStatusMeta> = {
  published: { label: "Active", color: "#1f9d6b" },
  active: { label: "Active", color: "#1f9d6b" },
  pending: { label: "Pending", color: "#c98a00" },
  paused: { label: "Paused", color: "#c98a00" },
  draft: { label: "Draft", color: "#a4a8b0" },
  rejected: { label: "Rejected", color: "#d6453d" },
};

export function statusMeta(status: string | null | undefined): AgentStatusMeta {
  const key = (status || "").toLowerCase();
  if (STATUS_META[key]) return STATUS_META[key];
  const label = key ? key.charAt(0).toUpperCase() + key.slice(1) : "Unknown";
  return { label, color: "#a4a8b0" };
}

/** Group ordering for the "Status" grouping (known states first). */
export const STATUS_GROUP_ORDER = [
  "published",
  "active",
  "pending",
  "paused",
  "draft",
  "rejected",
];

/* ---------------- model ---------------- */

export function modelLabel(model: ModelInfo | null | undefined): string {
  return (
    model?.model_display_name ||
    model?.config_name ||
    model?.provider_name ||
    ""
  );
}

export function ModelCell({
  model,
  className,
}: {
  model: ModelInfo | null | undefined;
  className?: string;
}) {
  const name = modelLabel(model);
  const provider = model?.provider_name;
  const iconUrl = model?.provider_icon_url ?? null;

  if (!name) {
    return (
      <span
        className={cn(
          "flex items-center gap-1.5 text-[12px] text-muted-foreground",
          className
        )}
      >
        <span className="grid h-[17px] w-[17px] shrink-0 place-items-center rounded-[5px] border border-dashed border-border text-muted-foreground">
          <MoreHorizontal className="h-2.5 w-2.5" />
        </span>
        <span className="truncate">Unknown model</span>
      </span>
    );
  }

  return (
    <span
      className={cn(
        "flex items-center gap-1.5 text-[12px] font-normal text-muted-foreground",
        className
      )}
    >
      {iconUrl ? (
        <span className="grid h-[17px] w-[17px] shrink-0 place-items-center overflow-hidden rounded-[5px] dark:bg-white/85 dark:p-[2.5px] dark:ring-1 dark:ring-white/10">
          <Image
            src={iconUrl}
            alt={provider || "Model"}
            width={17}
            height={17}
            className="h-full w-full object-contain"
          />
        </span>
      ) : (
        <span className="grid h-[17px] w-[17px] shrink-0 place-items-center rounded-[5px] bg-muted text-[8px] font-medium text-muted-foreground">
          {(provider || name).slice(0, 2).toUpperCase()}
        </span>
      )}
      <span className="truncate">{name}</span>
      {provider && (
        <span className="shrink-0 text-[11px] font-light text-muted-foreground/70">
          ({provider})
        </span>
      )}
    </span>
  );
}

/* ---------------- status cell ---------------- */

export function StatusCell({
  status,
  dotOnly,
  className,
}: {
  status: string | null | undefined;
  dotOnly?: boolean;
  className?: string;
}) {
  const { label, color } = statusMeta(status);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-[12px] font-normal",
            className
          )}
          style={{ color: dotOnly ? undefined : color }}
        >
          <span
            className="h-[7px] w-[7px] shrink-0 rounded-full"
            style={{ backgroundColor: color }}
          />
          {!dotOnly && label}
        </span>
      </TooltipTrigger>
      <TooltipContent>{label}</TooltipContent>
    </Tooltip>
  );
}

/* ---------------- active tasks ---------------- */

export function TasksCell({
  count,
  className,
}: {
  count: number;
  className?: string;
}) {
  if (!count) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex items-center text-[12px] text-muted-foreground/70",
              className
            )}
          >
            —
          </span>
        </TooltipTrigger>
        <TooltipContent>No active tasks</TooltipContent>
      </Tooltip>
    );
  }
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 text-[12px] text-muted-foreground",
            className
          )}
        >
          <Activity className="h-3.5 w-3.5" strokeWidth={1.7} />
          <span className="inline-grid h-[18px] min-w-[18px] place-items-center rounded-md bg-primary/10 px-1.5 text-[11px] font-medium text-primary">
            {count}
          </span>
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {count} active task{count > 1 ? "s" : ""} running
      </TooltipContent>
    </Tooltip>
  );
}

/* ---------------- tools stack ---------------- */

export function ToolsCell({
  agent,
  className,
}: {
  agent: Agent;
  className?: string;
}) {
  const tools = getToolAvatars(agent);

  if (tools.length === 0) {
    return (
      <Tooltip>
        <TooltipTrigger asChild>
          <span
            className={cn(
              "inline-flex items-center whitespace-nowrap text-[12px] text-muted-foreground/70",
              className
            )}
          >
            No tools
          </span>
        </TooltipTrigger>
        <TooltipContent>No tools connected</TooltipContent>
      </Tooltip>
    );
  }

  const shown = tools.slice(0, 4);
  const extra = tools.length - shown.length;

  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span className={cn("inline-flex items-center", className)}>
          <span className="flex -space-x-1.5">
            {shown.map((tool, i) => (
              <img
                key={i}
                src={tool.imageUrl}
                alt={tool.name}
                className="h-[21px] w-[21px] rounded-md border-[1.5px] border-background bg-white object-contain"
              />
            ))}
          </span>
          {extra > 0 && (
            <span className="ml-1.5 text-[11px] font-medium text-muted-foreground">
              +{extra}
            </span>
          )}
        </span>
      </TooltipTrigger>
      <TooltipContent className="max-w-[240px]">
        Tools: {tools.map((t) => t.name).join(", ")}
      </TooltipContent>
    </Tooltip>
  );
}
