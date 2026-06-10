"use client";

import { useTranslations } from "next-intl";
import Image from "next/image";
import { Activity, MoreHorizontal } from "lucide-react";
import { StatusDot } from "@/components/CollectionView";
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
  /** Stable identity used for tabs / grouping (statuses with the same label key
   *  merge — e.g. published + active). For unknown statuses it's the raw value. */
  labelKey: string;
  color: string;
  known: boolean;
}

const STATUS_META: Record<string, { labelKey: string; color: string }> = {
  published: { labelKey: "statusActive", color: "#1f9d6b" },
  active: { labelKey: "statusActive", color: "#1f9d6b" },
  pending: { labelKey: "statusPending", color: "#c98a00" },
  paused: { labelKey: "statusPaused", color: "#c98a00" },
  draft: { labelKey: "statusDraft", color: "#a4a8b0" },
  rejected: { labelKey: "statusRejected", color: "#d6453d" },
};

export function statusMeta(status: string | null | undefined): AgentStatusMeta {
  const key = (status || "").toLowerCase();
  if (STATUS_META[key]) return { ...STATUS_META[key], known: true };
  return { labelKey: key || "unknown", color: "#a4a8b0", known: false };
}

/** Resolve a status into its localized display label (handles unknown). */
export function agentStatusLabel(
  t: (key: string) => string,
  status: string | null | undefined
): string {
  const key = (status || "").toLowerCase();
  if (STATUS_META[key]) return t(STATUS_META[key].labelKey);
  return key ? key.charAt(0).toUpperCase() + key.slice(1) : t("unknown");
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
  const t = useTranslations("AgentsPage.view");
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
        <span className="truncate">{t("unknownModel")}</span>
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
            alt={provider || t("modelAlt")}
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
  const t = useTranslations("AgentsPage.view");
  const { color } = statusMeta(status);
  const label = agentStatusLabel(t, status);
  return (
    <StatusDot
      color={color}
      label={label}
      dotOnly={dotOnly}
      tooltip={label}
      className={cn("text-[12px] font-normal", className)}
    />
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
  const tt = useTranslations("AgentsPage.view");
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
        <TooltipContent>{tt("noActiveTasks")}</TooltipContent>
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
        {tt("activeTasksRunning", { count })}
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
  const tl = useTranslations("AgentsPage.view");
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
            {tl("noTools")}
          </span>
        </TooltipTrigger>
        <TooltipContent>{tl("noToolsConnected")}</TooltipContent>
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
        {tl("toolsList", { names: tools.map((tool) => tool.name).join(", ") })}
      </TooltipContent>
    </Tooltip>
  );
}
