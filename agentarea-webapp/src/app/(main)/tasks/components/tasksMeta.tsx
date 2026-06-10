"use client";

import { useTranslations } from "next-intl";
import { Calendar } from "lucide-react";
import { AgentChip, StatusDot } from "@/components/CollectionView";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export { AGENT_COLOR } from "@/components/CollectionView";

/* ---------------- status ---------------- */

export interface TaskStatusMeta {
  /** Coarse status bucket used for tabs + grouping. */
  key: "run" | "input" | "pending" | "done" | "fail";
  /** Keys under `TasksPage.view` for the localized label + tooltip. */
  labelKey: string;
  tipKey: string;
  color: string;
}

const STATUS_BY_KEY: Record<TaskStatusMeta["key"], TaskStatusMeta> = {
  run: { key: "run", labelKey: "runLabel", tipKey: "runTip", color: "#2252b3" },
  input: { key: "input", labelKey: "inputLabel", tipKey: "inputTip", color: "#c98a00" },
  pending: { key: "pending", labelKey: "pendingLabel", tipKey: "pendingTip", color: "#8a8f98" },
  done: { key: "done", labelKey: "doneLabel", tipKey: "doneTip", color: "#1f9d6b" },
  fail: { key: "fail", labelKey: "failLabel", tipKey: "failTip", color: "#d6453d" },
};

/** Order known status buckets appear in tabs and grouping. */
export const STATUS_GROUP_ORDER: TaskStatusMeta["key"][] = [
  "run",
  "input",
  "pending",
  "done",
  "fail",
];

/** Map a raw backend status onto one of the five display buckets. */
export function statusMeta(status: string | null | undefined): TaskStatusMeta {
  const s = (status || "").toLowerCase();
  if (/run|progress|executing|started/.test(s)) return STATUS_BY_KEY.run;
  if (/input|approval|waiting|blocked|review/.test(s)) return STATUS_BY_KEY.input;
  if (/complete|success|done|finished/.test(s)) return STATUS_BY_KEY.done;
  if (/fail|error|cancel|reject/.test(s)) return STATUS_BY_KEY.fail;
  return STATUS_BY_KEY.pending;
}

/* ---------------- agent ---------------- */

/* ---------------- cells ---------------- */

export function StatusCell({
  status,
  dotOnly,
  className,
}: {
  status: string | null | undefined;
  dotOnly?: boolean;
  className?: string;
}) {
  const t = useTranslations("TasksPage.view");
  const { key, labelKey, tipKey, color } = statusMeta(status);
  const running = key === "run";
  const label = t(labelKey);
  return (
    <StatusDot
      color={color}
      label={<span className="collection-status-label">{label}</span>}
      dotOnly={dotOnly}
      pulse={running}
      tooltip={
        <>
          {label} — {t(tipKey)}
        </>
      }
      className={cn("text-[12px] font-normal", className)}
    />
  );
}

export function AgentCell({
  name,
  size = 18,
  className,
}: {
  name: string | null | undefined;
  size?: number;
  className?: string;
}) {
  return <AgentChip name={name} size={size} className={className} />;
}

export function CostCell({
  cost,
  className,
}: {
  cost: number | null | undefined;
  className?: string;
}) {
  const t = useTranslations("TasksPage.view");
  const has = cost != null && !Number.isNaN(cost);
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "font-mono text-[12px] tabular-nums",
            has ? "text-foreground/80" : "text-muted-foreground/70",
            className
          )}
        >
          {has ? `$${cost!.toFixed(4)}` : "—"}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {has ? t("runCost", { cost: `$${cost!.toFixed(4)}` }) : t("noCost")}
      </TooltipContent>
    </Tooltip>
  );
}

/** "14:05" — 24h clock, shared by the list date cell and the card footer. */
export function fmtTime(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "—";
  return d.toLocaleTimeString("en-US", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
}

export function CreatedCell({
  iso,
  className,
}: {
  iso: string | null | undefined;
  className?: string;
}) {
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime()))
    return <span className={cn("text-muted-foreground/70", className)}>—</span>;
  const date = d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  return (
    <span className={cn("flex flex-col gap-px text-[11.5px] leading-tight", className)}>
      <span className="text-foreground/70">{date}</span>
      <span className="font-mono tabular-nums text-muted-foreground/80">
        {fmtTime(iso)}
      </span>
    </span>
  );
}

/** Inline created-date chip — calendar icon + full date, with a tooltip
 *  spelling out that it's the creation date + time. Used in card footers. */
export function CreatedInline({
  iso,
  className,
}: {
  iso: string | null | undefined;
  className?: string;
}) {
  const t = useTranslations("TasksPage.view");
  const d = iso ? new Date(iso) : null;
  if (!d || Number.isNaN(d.getTime())) {
    return <span className={cn("text-muted-foreground/70", className)}>—</span>;
  }
  const date = d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
  const full = d.toLocaleString("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  });
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex shrink-0 items-center gap-1 tabular-nums",
            className
          )}
        >
          <Calendar className="h-3 w-3" strokeWidth={1.7} />
          {date}
        </span>
      </TooltipTrigger>
      <TooltipContent>{t("created", { date: full })}</TooltipContent>
    </Tooltip>
  );
}
