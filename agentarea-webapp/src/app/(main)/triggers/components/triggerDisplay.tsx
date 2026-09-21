import { createElement } from "react";
import { Clock, Zap } from "lucide-react";
import type { TriggerResponse } from "@/api/client/types.gen";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";
import { cn } from "@/lib/utils";

export interface TriggerCatalogEntry {
  id?: string;
  name?: string;
  /** Asset id kept for reference; render `icon_url`, not this. */
  icon?: string;
  /** Resolved by the API — the only thing the UI needs to draw a channel. */
  icon_url?: string | null;
  description?: string;
  kind?: string;
  webhook_type?: string;
  data_extractor?: string;
}

export type EnrichedTrigger = TriggerResponse & {
  agent_name?: string;
  next_run_at?: string | null;
};

export interface TriggerLike {
  trigger_type?: string;
  webhook_type?: string | null;
  data_extractor?: string | null;
  cron_expression?: string | null;
  is_active?: boolean;
  consecutive_failures?: number;
  failure_threshold?: number;
  config?: {
    webhook_type?: string | null;
    cron_expression?: string | null;
  } | null;
}

export function findTriggerCatalogEntry(
  trigger: TriggerLike,
  catalog: TriggerCatalogEntry[]
) {
  if (trigger.data_extractor) {
    const match = catalog.find(
      (entry) => entry.data_extractor === trigger.data_extractor
    );
    if (match) return match;
  }

  if (trigger.trigger_type === "cron") {
    return catalog.find((entry) => entry.id === "cron");
  }

  const webhookType = trigger.webhook_type || trigger.config?.webhook_type;
  return (
    catalog.find((entry) => entry.webhook_type === webhookType) ||
    catalog.find((entry) => entry.id === "webhook")
  );
}

// webhook_type only means anything for webhook triggers — the backend stores a
// "generic" default on cron triggers too, which must not mask the schedule.
function effectiveWebhookType(trigger?: TriggerLike) {
  if (!trigger || trigger.trigger_type === "cron") return "";
  return (
    trigger.webhook_type ||
    trigger.config?.webhook_type ||
    ""
  ).toLowerCase();
}

// For webhook triggers the trigger's own webhook_type wins over the catalog
// entry: channels missing from the catalog (e.g. github) fall back to the
// generic "webhook" entry, which must not mask the real event source.
export function getTriggerSourceKey(
  entry?: TriggerCatalogEntry | null,
  trigger?: TriggerLike
) {
  return (
    effectiveWebhookType(trigger) ||
    entry?.id ||
    entry?.webhook_type ||
    trigger?.trigger_type ||
    "webhook"
  ).toLowerCase();
}

/**
 * The catalog owns both the artwork and the name of a channel — which channels
 * exist grows by configuration, so nothing here may switch on the channel. The
 * API hands us a resolved `icon_url`; we draw it and ask no questions, and only
 * when it has none do we fall back to a glyph for the trigger's kind.
 */
export function renderTriggerIcon(
  entry?: TriggerCatalogEntry | null,
  trigger?: TriggerLike,
  className = "h-5 w-5"
) {
  if (entry?.icon_url) {
    return createElement("img", {
      src: entry.icon_url,
      alt: "",
      "aria-hidden": true,
      className: cn("shrink-0 object-contain", className),
    });
  }
  // A channel the catalog ships no artwork for still has to show *something* —
  // returning nothing left an empty tinted tile with no mark in it at all. The
  // split is on `trigger_type`, a column on the model, not on which channel it
  // is: that stays catalog-driven.
  return createElement(trigger?.trigger_type === "cron" ? Clock : Zap, {
    "aria-hidden": true,
    strokeWidth: 1.85,
    className: cn("shrink-0", className),
  });
}

/**
 * The event source a trigger listens to, as a tile: the channel's own logo when
 * the catalog has one, else the kind's glyph, on a graphite tile hued by the
 * source key. Every non-cron trigger used to share one violet tint, so a list
 * of GitHub, Slack and Stripe hooks read as one repeated mark.
 */
export function TriggerSourceMark({
  entry,
  trigger,
  size = 28,
}: {
  entry?: TriggerCatalogEntry | null;
  trigger?: TriggerLike;
  size?: number;
}) {
  return (
    <EntityAvatar
      size={size}
      hue={deterministicHue(getTriggerSourceKey(entry, trigger))}
      icon={renderTriggerIcon(entry, trigger, "h-full w-full")}
      iconScale={entry?.icon_url ? 0.68 : 0.5}
      aria-hidden
    />
  );
}

export function getTriggerDisplayName(
  trigger: TriggerLike,
  entry?: TriggerCatalogEntry | null
) {
  return entry?.name ?? trigger.trigger_type ?? "";
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

const WEBHOOK_SCHEDULE_LABEL: Record<string, string> = {
  slack: "On Slack event",
  telegram: "On Telegram message",
  discord: "On Discord message",
  github: "On GitHub event",
  gmail: "On new email",
  email: "On new email",
  stripe: "On Stripe event",
  linear: "On Linear event",
  teams: "On Teams message",
  generic: "On incoming request",
};

/** Human description of when a trigger fires, shown in the listing. */
export function describeTriggerSchedule(trigger: TriggerLike): string {
  if (trigger?.trigger_type === "cron") {
    return describeCronExpression(
      trigger.cron_expression ?? trigger.config?.cron_expression
    );
  }
  if (trigger?.trigger_type === "polling") {
    return "Polls for updates";
  }
  const webhookType = (
    trigger?.webhook_type ||
    trigger?.config?.webhook_type ||
    ""
  ).toLowerCase();
  return WEBHOOK_SCHEDULE_LABEL[webhookType] || "On incoming request";
}

export type TriggerHealth = "active" | "paused" | "error";

/**
 * Derive the listing status pill. A trigger that has hit its failure threshold
 * reads as "error"; otherwise it's "active" or "paused" by its enabled flag.
 */
export function getTriggerHealth(trigger: TriggerLike): TriggerHealth {
  const failures = Number(trigger?.consecutive_failures ?? 0);
  const threshold = Number(trigger?.failure_threshold ?? 0);
  if (threshold > 0 && failures >= threshold) return "error";
  return trigger?.is_active ? "active" : "paused";
}

/**
 * Cost of one run, or of a trigger's history. Sub-dollar amounts keep four
 * decimals: a run that costs $0.0071 must not read as "$0.01", which is what
 * the two-decimal money format everywhere else would make of it.
 */
export function formatTriggerCost(value: number): string {
  const fractionDigits = Math.abs(value) > 0 && Math.abs(value) < 1 ? 4 : 2;
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: fractionDigits,
    maximumFractionDigits: fractionDigits,
  }).format(value);
}

/** Compact relative time like "in 14h" / "3m ago" (matches the design). */
export function formatCompactDistance(value: Date | string | number): string {
  const target = new Date(value).getTime();
  if (Number.isNaN(target)) return "—";
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
