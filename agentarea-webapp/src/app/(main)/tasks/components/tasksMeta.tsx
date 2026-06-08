"use client";

import { Bot } from "lucide-react";
import { Tile } from "@/components/CollectionView";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/* ---------------- status ---------------- */

export interface TaskStatusMeta {
  /** Coarse status bucket used for tabs + grouping. */
  key: "run" | "input" | "pending" | "done" | "fail";
  label: string;
  color: string;
  tip: string;
}

const STATUS_BY_KEY: Record<TaskStatusMeta["key"], TaskStatusMeta> = {
  run: {
    key: "run",
    label: "Running",
    color: "#2252b3",
    tip: "Agent is working on this task",
  },
  input: {
    key: "input",
    label: "Input required",
    color: "#c98a00",
    tip: "Waiting for your approval to continue",
  },
  pending: {
    key: "pending",
    label: "Pending",
    color: "#8a8f98",
    tip: "Queued, not started yet",
  },
  done: {
    key: "done",
    label: "Completed",
    color: "#1f9d6b",
    tip: "Finished successfully",
  },
  fail: {
    key: "fail",
    label: "Failed",
    color: "#d6453d",
    tip: "Task ended with an error",
  },
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

/** Single agent accent — agents don't carry per-agent icons yet, so (like the
 *  /agents page) every agent renders with the Bot glyph in this colour. */
export const AGENT_COLOR = "#5e6ad2";

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
  const { key, label, color, tip } = statusMeta(status);
  const running = key === "run";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex items-center gap-1.5 whitespace-nowrap text-[12px] font-normal",
            className
          )}
          style={{ color: dotOnly ? undefined : color }}
        >
          <span
            className={cn(
              "h-[7px] w-[7px] shrink-0 rounded-full",
              running && "motion-safe:animate-pulse"
            )}
            style={{ backgroundColor: color }}
          />
          {!dotOnly && label}
        </span>
      </TooltipTrigger>
      <TooltipContent>
        {label} — {tip}
      </TooltipContent>
    </Tooltip>
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
  const display = name || "Unknown agent";
  return (
    <Tooltip>
      <TooltipTrigger asChild>
        <span
          className={cn(
            "inline-flex items-center gap-2 text-[12.5px] text-foreground/80",
            className
          )}
        >
          <Tile color={AGENT_COLOR} icon={Bot} size={size} />
          <span className="truncate">{display}</span>
        </span>
      </TooltipTrigger>
      <TooltipContent>{display}</TooltipContent>
    </Tooltip>
  );
}

export function CostCell({
  cost,
  className,
}: {
  cost: number | null | undefined;
  className?: string;
}) {
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
        {has ? `Run cost: $${cost!.toFixed(4)}` : "No cost recorded"}
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
