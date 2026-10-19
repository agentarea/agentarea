import { createElement } from "react";
import { Clock } from "lucide-react";
import type { TriggerResponse } from "@/api/client/types.gen";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { formatMoney } from "@/lib/money";
import { cn } from "@/lib/utils";
import { getValidTimestamp } from "@/utils/dateUtils";

export type EnrichedTrigger = TriggerResponse & {
  agent_name?: string;
  next_run_at?: string | null;
};

export interface TriggerLike {
  trigger_type?: string;
  cron_expression?: string | null;
  session?: { continue?: boolean | null } | null;
  is_active?: boolean;
  status?: string;
  consecutive_failures?: number;
  failure_threshold?: number;
}

/**
 * What starts this automation, which is the distinction that matters when
 * reading the list: a conversation whose next message joins the same task, an
 * event that each starts its own, or the clock. A trigger is a schedule or a
 * subscription to a stream; which providers feed the stream is the catalog's
 * business and never decides the lane.
 */
export type TriggerLane = "channel" | "event" | "schedule";

export function getTriggerLane(trigger: TriggerLike): TriggerLane {
  if (trigger.trigger_type === "cron") return "schedule";
  return trigger.session?.continue ? "channel" : "event";
}

/** The glyph of what fires the trigger: the clock, or the stream it listens to. */
export function renderTriggerIcon(trigger?: TriggerLike, className = "h-5 w-5") {
  return createElement(
    trigger?.trigger_type === "cron" ? Clock : ENTITY_ICONS.stream,
    {
      "aria-hidden": true,
      strokeWidth: 1.85,
      className: cn("shrink-0", className),
    }
  );
}

/** What fires the trigger, as a graphite tile hued by its type. */
export function TriggerSourceMark({
  trigger,
  size = 28,
}: {
  trigger?: TriggerLike;
  size?: number;
}) {
  return (
    <EntityAvatar
      size={size}
      hue={deterministicHue(trigger?.trigger_type ?? "stream")}
      icon={renderTriggerIcon(trigger, "h-full w-full")}
      iconScale={0.5}
      aria-hidden
    />
  );
}

/** The trigger's type in the active locale: `typeLabel` resolves `TriggersPage.type.<trigger_type>`. */
export function getTriggerDisplayName(
  trigger: TriggerLike,
  typeLabel: (type: string) => string
) {
  return trigger.trigger_type ? typeLabel(trigger.trigger_type) : "";
}

/* -------------------------------------------------------------------------- */
/* Schedule / status helpers                                                  */
/* -------------------------------------------------------------------------- */

const CRON_DAY_NAMES = [
  "Sunday",
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
];

function formatClock(hour: number, minute: number): string {
  if (hour === 0 && minute === 0) return "midnight";
  if (hour === 12 && minute === 0) return "noon";
  const period = hour < 12 ? "AM" : "PM";
  const hour12 = hour % 12 === 0 ? 12 : hour % 12;
  return `${hour12}:${String(minute).padStart(2, "0")} ${period}`;
}

function ordinalSuffix(n: number): string {
  if (n >= 11 && n <= 13) return "th";
  return ["th", "st", "nd", "rd"][n % 10] ?? "th";
}

/**
 * Turn a 5- or 6-field cron expression into a short, human phrase that matches
 * the Automation listing design (e.g. "Every day at 7:00 AM", "Every 5 minutes",
 * "Weekdays at 8:30 AM"). Falls back to the raw expression for shapes it can't
 * confidently describe.
 */
export function describeCronExpression(expr?: string | null): string {
  if (!expr) return "Custom schedule";
  let parts = expr.trim().split(/\s+/);
  if (parts.length === 6) parts = parts.slice(1); // drop the seconds field
  if (parts.length !== 5) return expr;

  const [min, hour, dom, , dow] = parts;

  // Every N minutes — */N * * * *
  if (min.startsWith("*/") && hour === "*" && dom === "*" && dow === "*") {
    const n = min.slice(2);
    return n === "1" ? "Every minute" : `Every ${n} minutes`;
  }
  if (min === "*" && hour === "*" && dom === "*" && dow === "*") {
    return "Every minute";
  }

  // Hourly — M * * * *  or  M */N * * *
  if (hour === "*" && dom === "*" && dow === "*" && /^\d+$/.test(min)) {
    return min === "0"
      ? "Every hour"
      : `Every hour at :${min.padStart(2, "0")}`;
  }
  if (hour.startsWith("*/") && dom === "*" && dow === "*") {
    return `Every ${hour.slice(2)} hours`;
  }

  const timeValid = /^\d+$/.test(min) && /^\d+$/.test(hour);
  const time = timeValid
    ? formatClock(parseInt(hour, 10), parseInt(min, 10))
    : null;

  if (timeValid && dom === "*") {
    // Weekday / weekend ranges
    if (dow === "1-5") return `Weekdays at ${time}`;
    if (dow === "0,6" || dow === "6,0" || dow === "0,6,")
      return `Weekends at ${time}`;
    // A single day of the week
    if (/^[0-6]$/.test(dow)) {
      return `Every ${CRON_DAY_NAMES[parseInt(dow, 10)]} at ${time}`;
    }
    // Daily
    if (dow === "*") return `Every day at ${time}`;
  }

  // Monthly — M H D * *
  if (timeValid && /^\d+$/.test(dom) && dow === "*") {
    const day = parseInt(dom, 10);
    return `Monthly on the ${day}${ordinalSuffix(day)} at ${time}`;
  }

  return expr;
}

/** When a schedule fires, in words; a stream trigger's phrase is translated by its caller. */
export function describeTriggerSchedule(trigger: TriggerLike): string {
  return describeCronExpression(trigger.cron_expression);
}

export type TriggerHealth = "active" | "paused" | "error" | "needs_owner";

/**
 * Derive the listing status pill. A trigger whose configurer lost access reads
 * as "needs_owner"; one that has hit its failure threshold reads as "error";
 * otherwise it's "active" or "paused" by its enabled flag.
 */
export function getTriggerHealth(trigger: TriggerLike): TriggerHealth {
  if (trigger?.status === "needs_owner") return "needs_owner";
  const failures = Number(trigger?.consecutive_failures ?? 0);
  const threshold = Number(trigger?.failure_threshold ?? 0);
  if (threshold > 0 && failures >= threshold) return "error";
  return trigger?.is_active ? "active" : "paused";
}

/**
 * Cost of one run, or of a trigger's history, in the workspace's billing
 * currency (see `useCurrency()` / C2). `currency: null` (loading, or a
 * failed lookup) renders without a currency symbol — never guesses USD.
 */
export function formatTriggerCost(
  value: number,
  currency: string | null = null,
  locale: string = "en"
): string {
  return formatMoney(value, currency, locale);
}

/** Compact relative time like "in 14h" / "3m ago" (matches the design). */
export function formatCompactDistance(value: Date | string | number): string {
  const target =
    typeof value === "string"
      ? getValidTimestamp(value)
      : new Date(value).getTime();
  if (target === null || Number.isNaN(target)) return "—";
  const diff = target - Date.now();
  const seconds = Math.round(Math.abs(diff) / 1000);

  let label: string;
  if (seconds < 45) return "now";
  else if (seconds < 3600) label = `${Math.round(seconds / 60)}m`;
  else if (seconds < 86400) label = `${Math.round(seconds / 3600)}h`;
  else if (seconds < 86400 * 30) label = `${Math.round(seconds / 86400)}d`;
  else if (seconds < 86400 * 365)
    label = `${Math.round(seconds / (86400 * 30))}mo`;
  else label = `${Math.round(seconds / (86400 * 365))}y`;

  return diff >= 0 ? `in ${label}` : `${label} ago`;
}
