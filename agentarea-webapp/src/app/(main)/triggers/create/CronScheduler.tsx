"use client";

import { useEffect, useMemo, useState } from "react";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { cn } from "@/lib/utils";

type Frequency = "every_minute" | "hourly" | "daily" | "weekly" | "monthly" | "custom";

const DAYS_OF_WEEK = [
  { value: "1", label: "Monday" },
  { value: "2", label: "Tuesday" },
  { value: "3", label: "Wednesday" },
  { value: "4", label: "Thursday" },
  { value: "5", label: "Friday" },
  { value: "6", label: "Saturday" },
  { value: "0", label: "Sunday" },
];

const HOURS = Array.from({ length: 24 }, (_, i) => ({
  value: String(i),
  label: i.toString().padStart(2, "0"),
}));

const MINUTES = Array.from({ length: 60 }, (_, i) => ({
  value: String(i),
  label: i.toString().padStart(2, "0"),
}));

const DAYS_OF_MONTH = Array.from({ length: 31 }, (_, i) => ({
  value: String(i + 1),
  label: String(i + 1),
}));

const HOURLY_INTERVALS = [
  { value: "1", label: "Every hour" },
  { value: "2", label: "Every 2 hours" },
  { value: "3", label: "Every 3 hours" },
  { value: "4", label: "Every 4 hours" },
  { value: "6", label: "Every 6 hours" },
  { value: "8", label: "Every 8 hours" },
  { value: "12", label: "Every 12 hours" },
];

const MINUTE_INTERVALS = [
  { value: "1", label: "Every minute" },
  { value: "5", label: "Every 5 minutes" },
  { value: "10", label: "Every 10 minutes" },
  { value: "15", label: "Every 15 minutes" },
  { value: "30", label: "Every 30 minutes" },
];

function parseCron(expr: string): {
  frequency: Frequency;
  minute: string;
  hour: string;
  dayOfMonth: string;
  dayOfWeek: string;
  hourInterval: string;
  minuteInterval: string;
} {
  const defaults = {
    frequency: "daily" as Frequency,
    minute: "0",
    hour: "9",
    dayOfMonth: "1",
    dayOfWeek: "1",
    hourInterval: "1",
    minuteInterval: "5",
  };

  if (!expr) return defaults;

  const parts = expr.trim().split(/\s+/);
  if (parts.length !== 5) return { ...defaults, frequency: "custom" };

  const [min, hr, dom, , dow] = parts;

  // Every N minutes: */N * * * *
  if (min.startsWith("*/") && hr === "*" && dom === "*" && dow === "*") {
    const interval = min.slice(2);
    if (interval === "1") {
      return { ...defaults, frequency: "every_minute", minuteInterval: "1" };
    }
    return { ...defaults, frequency: "every_minute", minuteInterval: interval };
  }

  // Hourly: M */N * * * or M * * * *
  if (hr.startsWith("*/") && dom === "*" && dow === "*") {
    return { ...defaults, frequency: "hourly", minute: min, hourInterval: hr.slice(2) };
  }
  if (!min.includes("*") && hr === "*" && dom === "*" && dow === "*") {
    return { ...defaults, frequency: "hourly", minute: min, hourInterval: "1" };
  }

  // Weekly: M H * * D
  if (!min.includes("*") && !hr.includes("*") && dom === "*" && dow !== "*") {
    return { ...defaults, frequency: "weekly", minute: min, hour: hr, dayOfWeek: dow };
  }

  // Monthly: M H D * *
  if (!min.includes("*") && !hr.includes("*") && dom !== "*" && dow === "*") {
    return { ...defaults, frequency: "monthly", minute: min, hour: hr, dayOfMonth: dom };
  }

  // Daily: M H * * *
  if (!min.includes("*") && !hr.includes("*") && dom === "*" && dow === "*") {
    return { ...defaults, frequency: "daily", minute: min, hour: hr };
  }

  return { ...defaults, frequency: "custom" };
}

function buildCron(
  frequency: Frequency,
  minute: string,
  hour: string,
  dayOfMonth: string,
  dayOfWeek: string,
  hourInterval: string,
  minuteInterval: string
): string {
  switch (frequency) {
    case "every_minute":
      return minuteInterval === "1" ? "* * * * *" : `*/${minuteInterval} * * * *`;
    case "hourly":
      return hourInterval === "1" ? `${minute} * * * *` : `${minute} */${hourInterval} * * *`;
    case "daily":
      return `${minute} ${hour} * * *`;
    case "weekly":
      return `${minute} ${hour} * * ${dayOfWeek}`;
    case "monthly":
      return `${minute} ${hour} ${dayOfMonth} * *`;
    default:
      return "0 9 * * *";
  }
}

function describeCron(
  frequency: Frequency,
  minute: string,
  hour: string,
  dayOfMonth: string,
  dayOfWeek: string,
  hourInterval: string,
  minuteInterval: string
): string {
  const time = `${hour.padStart(2, "0")}:${minute.padStart(2, "0")}`;
  const dayName = DAYS_OF_WEEK.find((d) => d.value === dayOfWeek)?.label ?? dayOfWeek;
  const suffix = (n: number) => {
    if (n >= 11 && n <= 13) return "th";
    switch (n % 10) {
      case 1: return "st";
      case 2: return "nd";
      case 3: return "rd";
      default: return "th";
    }
  };

  switch (frequency) {
    case "every_minute":
      return minuteInterval === "1"
        ? "Runs every minute"
        : `Runs every ${minuteInterval} minutes`;
    case "hourly":
      if (hourInterval === "1") return `Runs every hour at minute ${minute}`;
      return `Runs every ${hourInterval} hours at minute ${minute}`;
    case "daily":
      return `Runs daily at ${time}`;
    case "weekly":
      return `Runs every ${dayName} at ${time}`;
    case "monthly": {
      const dom = parseInt(dayOfMonth);
      return `Runs on the ${dom}${suffix(dom)} of every month at ${time}`;
    }
    case "custom":
      return "Custom cron expression";
  }
}

interface CronSchedulerProps {
  defaultValue?: string;
  name: string;
}

export function CronScheduler({ defaultValue = "", name }: CronSchedulerProps) {
  const parsed = useMemo(() => parseCron(defaultValue), [defaultValue]);

  const [frequency, setFrequency] = useState<Frequency>(parsed.frequency);
  const [minute, setMinute] = useState(parsed.minute);
  const [hour, setHour] = useState(parsed.hour);
  const [dayOfMonth, setDayOfMonth] = useState(parsed.dayOfMonth);
  const [dayOfWeek, setDayOfWeek] = useState(parsed.dayOfWeek);
  const [hourInterval, setHourInterval] = useState(parsed.hourInterval);
  const [minuteInterval, setMinuteInterval] = useState(parsed.minuteInterval);
  const [customExpr, setCustomExpr] = useState(defaultValue);

  const cronExpr =
    frequency === "custom"
      ? customExpr
      : buildCron(frequency, minute, hour, dayOfMonth, dayOfWeek, hourInterval, minuteInterval);

  const description =
    frequency === "custom"
      ? `Custom: ${customExpr}`
      : describeCron(frequency, minute, hour, dayOfMonth, dayOfWeek, hourInterval, minuteInterval);

  // Sync custom expr when switching to custom
  useEffect(() => {
    if (frequency === "custom" && !customExpr) {
      setCustomExpr("0 9 * * *");
    }
  }, [frequency]);

  return (
    <div className="space-y-4">
      <input type="hidden" name={name} value={cronExpr} />

      {/* Frequency selector */}
      <div className="space-y-1.5">
        <Label className="text-sm">Frequency</Label>
        <div className="flex flex-wrap gap-1.5">
          {([
            ["every_minute", "Minutes"],
            ["hourly", "Hourly"],
            ["daily", "Daily"],
            ["weekly", "Weekly"],
            ["monthly", "Monthly"],
            ["custom", "Custom"],
          ] as [Frequency, string][]).map(([key, label]) => (
            <button
              key={key}
              type="button"
              onClick={() => setFrequency(key)}
              className={cn(
                "rounded-md px-3 py-1.5 text-xs font-medium transition-colors",
                frequency === key
                  ? "bg-primary text-primary-foreground"
                  : "bg-muted text-muted-foreground hover:bg-muted/80"
              )}
            >
              {label}
            </button>
          ))}
        </div>
      </div>

      {/* Frequency-specific options */}
      <div className="flex flex-wrap items-end gap-3">
        {frequency === "every_minute" && (
          <div className="space-y-1.5">
            <Label className="text-sm">Interval</Label>
            <Select value={minuteInterval} onValueChange={setMinuteInterval}>
              <SelectTrigger className="w-[180px]">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MINUTE_INTERVALS.map((m) => (
                  <SelectItem key={m.value} value={m.value}>
                    {m.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        )}

        {frequency === "hourly" && (
          <>
            <div className="space-y-1.5">
              <Label className="text-sm">Interval</Label>
              <Select value={hourInterval} onValueChange={setHourInterval}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HOURLY_INTERVALS.map((h) => (
                    <SelectItem key={h.value} value={h.value}>
                      {h.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-sm">At minute</Label>
              <Select value={minute} onValueChange={setMinute}>
                <SelectTrigger className="w-[80px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {MINUTES.filter((_, i) => i % 5 === 0).map((m) => (
                    <SelectItem key={m.value} value={m.value}>
                      :{m.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </>
        )}

        {frequency === "daily" && (
          <div className="flex items-end gap-2">
            <div className="space-y-1.5">
              <Label className="text-sm">Time</Label>
              <div className="flex items-center gap-1">
                <Select value={hour} onValueChange={setHour}>
                  <SelectTrigger className="w-[72px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {HOURS.map((h) => (
                      <SelectItem key={h.value} value={h.value}>
                        {h.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-sm text-muted-foreground">:</span>
                <Select value={minute} onValueChange={setMinute}>
                  <SelectTrigger className="w-[72px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MINUTES.filter((_, i) => i % 5 === 0).map((m) => (
                      <SelectItem key={m.value} value={m.value}>
                        {m.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </div>
        )}

        {frequency === "weekly" && (
          <>
            <div className="space-y-1.5">
              <Label className="text-sm">Day</Label>
              <Select value={dayOfWeek} onValueChange={setDayOfWeek}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DAYS_OF_WEEK.map((d) => (
                    <SelectItem key={d.value} value={d.value}>
                      {d.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-sm">Time</Label>
              <div className="flex items-center gap-1">
                <Select value={hour} onValueChange={setHour}>
                  <SelectTrigger className="w-[72px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {HOURS.map((h) => (
                      <SelectItem key={h.value} value={h.value}>
                        {h.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-sm text-muted-foreground">:</span>
                <Select value={minute} onValueChange={setMinute}>
                  <SelectTrigger className="w-[72px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MINUTES.filter((_, i) => i % 5 === 0).map((m) => (
                      <SelectItem key={m.value} value={m.value}>
                        {m.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </>
        )}

        {frequency === "monthly" && (
          <>
            <div className="space-y-1.5">
              <Label className="text-sm">Day of month</Label>
              <Select value={dayOfMonth} onValueChange={setDayOfMonth}>
                <SelectTrigger className="w-[80px]">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {DAYS_OF_MONTH.map((d) => (
                    <SelectItem key={d.value} value={d.value}>
                      {d.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="space-y-1.5">
              <Label className="text-sm">Time</Label>
              <div className="flex items-center gap-1">
                <Select value={hour} onValueChange={setHour}>
                  <SelectTrigger className="w-[72px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {HOURS.map((h) => (
                      <SelectItem key={h.value} value={h.value}>
                        {h.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <span className="text-sm text-muted-foreground">:</span>
                <Select value={minute} onValueChange={setMinute}>
                  <SelectTrigger className="w-[72px]">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {MINUTES.filter((_, i) => i % 5 === 0).map((m) => (
                      <SelectItem key={m.value} value={m.value}>
                        {m.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
          </>
        )}

        {frequency === "custom" && (
          <div className="space-y-1.5 flex-1">
            <Label className="text-sm">Cron expression</Label>
            <input
              type="text"
              value={customExpr}
              onChange={(e) => setCustomExpr(e.target.value)}
              placeholder="0 9 * * 1-5"
              className="flex h-9 w-full rounded-md border border-input bg-transparent px-3 py-1 text-sm font-mono shadow-xs transition-colors placeholder:text-muted-foreground focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring"
            />
            <p className="text-[10px] text-muted-foreground">
              minute hour day month weekday
            </p>
          </div>
        )}
      </div>

      {/* Preview */}
      <div className="flex items-center gap-2 rounded-md bg-muted/50 px-3 py-2">
        <span className="text-xs text-muted-foreground">{description}</span>
        {frequency !== "custom" && (
          <code className="ml-auto text-[10px] font-mono text-muted-foreground/60">
            {cronExpr}
          </code>
        )}
      </div>
    </div>
  );
}
