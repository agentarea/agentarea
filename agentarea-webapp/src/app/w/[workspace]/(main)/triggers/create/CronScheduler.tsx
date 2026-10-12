"use client";

import { useEffect, useId, useMemo, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { SegmentedControl } from "@/components/ui/segmented-control";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

type Frequency =
  | "every_minute"
  | "hourly"
  | "daily"
  | "weekly"
  | "monthly"
  | "custom";

const FREQUENCIES: Frequency[] = [
  "every_minute",
  "hourly",
  "daily",
  "weekly",
  "monthly",
  "custom",
];

// Monday first, as a week reads; values are cron's day-of-week numbers.
const DAYS_OF_WEEK = ["1", "2", "3", "4", "5", "6", "0"];

const range = (length: number, from = 0) =>
  Array.from({ length }, (_, i) => String(i + from));

const HOURS = range(24);
const MINUTES = range(60);
const DAYS_OF_MONTH = range(31, 1);
const HOURLY_INTERVALS = ["1", "2", "3", "4", "6", "8", "12"];
const MINUTE_INTERVALS = ["1", "5", "10", "15", "30"];

const pad = (value: string) => value.padStart(2, "0");

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

  const [min, hr, dom, month, dow] = parts;
  const custom = { ...defaults, frequency: "custom" as Frequency };

  // Presets can only represent schedules that run throughout the year.
  if (month !== "*") return custom;

  // Every N minutes: */N * * * *
  if (hr === "*" && dom === "*" && dow === "*") {
    const interval = min === "*" ? "1" : min.startsWith("*/") ? min.slice(2) : "";
    if (MINUTE_INTERVALS.includes(interval)) {
      return { ...defaults, frequency: "every_minute", minuteInterval: interval };
    }
  }

  if (!MINUTES.includes(min)) return custom;

  // Hourly: M */N * * * or M * * * *
  if (dom === "*" && dow === "*") {
    const interval = hr === "*" ? "1" : hr.startsWith("*/") ? hr.slice(2) : "";
    if (HOURLY_INTERVALS.includes(interval)) {
      return { ...defaults, frequency: "hourly", minute: min, hourInterval: interval };
    }
  }

  if (!HOURS.includes(hr)) return custom;

  // Weekly: M H * * D
  if (dom === "*" && DAYS_OF_WEEK.includes(dow)) {
    return { ...defaults, frequency: "weekly", minute: min, hour: hr, dayOfWeek: dow };
  }

  // Monthly: M H D * *
  if (DAYS_OF_MONTH.includes(dom) && dow === "*") {
    return { ...defaults, frequency: "monthly", minute: min, hour: hr, dayOfMonth: dom };
  }

  // Daily: M H * * *
  if (dom === "*" && dow === "*") {
    return { ...defaults, frequency: "daily", minute: min, hour: hr };
  }

  return custom;
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

function Field({
  label,
  htmlFor,
  children,
}: {
  label: string;
  htmlFor?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1.5">
      <Label htmlFor={htmlFor} className="text-xs text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  );
}

function OptionSelect({
  value,
  onChange,
  options,
  className,
  ariaLabel,
}: {
  value: string;
  onChange: (value: string) => void;
  options: { value: string; label: string }[];
  className: string;
  ariaLabel?: string;
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className={className} aria-label={ariaLabel}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        {options.map((option) => (
          <SelectItem key={option.value} value={option.value}>
            {option.label}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

interface CronSchedulerProps {
  defaultValue?: string;
  name: string;
  onChange?: (cronExpression: string) => void;
}

export function CronScheduler({
  defaultValue = "",
  name,
  onChange,
}: CronSchedulerProps) {
  const t = useTranslations("TriggersPage.create.cron");
  const locale = useLocale();
  const instanceId = useId();
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

  useEffect(() => {
    onChange?.(cronExpr);
  }, [cronExpr, onChange]);

  // 7 Jan 2024 was a Sunday, so day N of that week is cron's weekday N.
  const dayName = useMemo(() => {
    const format = new Intl.DateTimeFormat(locale, {
      weekday: "long",
      timeZone: "UTC",
    });
    return (value: string) =>
      format.format(new Date(Date.UTC(2024, 0, 7 + Number(value))));
  }, [locale]);

  const time = `${pad(hour)}:${pad(minute)}`;
  const description = {
    every_minute: t("runsEveryMinutes", { count: Number(minuteInterval) }),
    hourly: t("runsEveryHours", {
      count: Number(hourInterval),
      minute: pad(minute),
    }),
    daily: t("runsDaily", { time }),
    weekly: t("runsWeekly", { day: dayName(dayOfWeek), time }),
    monthly: t("runsMonthly", { day: Number(dayOfMonth), time }),
    custom: t("runsCustom"),
  }[frequency];

  const hourOptions = HOURS.map((value) => ({ value, label: pad(value) }));
  const minuteOptions = MINUTES.map((value) => ({ value, label: pad(value) }));
  const timeField = (
    <Field label={t("time")}>
      <div className="flex items-center gap-1">
        <OptionSelect
          value={hour}
          onChange={setHour}
          options={hourOptions}
          className="w-[72px]"
          ariaLabel={t("hour")}
        />
        <span className="text-sm text-muted-foreground">:</span>
        <OptionSelect
          value={minute}
          onChange={setMinute}
          options={minuteOptions}
          className="w-[72px]"
          ariaLabel={t("minute")}
        />
      </div>
    </Field>
  );

  return (
    <div className="space-y-4">
      <input type="hidden" name={name} value={cronExpr} />

      <SegmentedControl
        items={FREQUENCIES.map((value) => ({
          value,
          label: t(`frequency.${value}`),
        }))}
        value={frequency}
        onChange={(key) => {
          if (key === "custom") setCustomExpr(cronExpr);
          setFrequency(key);
        }}
        layoutId={`cron-frequency-${instanceId}`}
        className="max-w-full"
        itemClassName="min-w-0"
      />

      <div className="flex flex-wrap items-end gap-3">
        {frequency === "every_minute" && (
          <Field label={t("interval")}>
            <OptionSelect
              value={minuteInterval}
              onChange={setMinuteInterval}
              options={MINUTE_INTERVALS.map((value) => ({
                value,
                label: t("everyMinutes", { count: Number(value) }),
              }))}
              className="w-[180px]"
            />
          </Field>
        )}

        {frequency === "hourly" && (
          <>
            <Field label={t("interval")}>
              <OptionSelect
                value={hourInterval}
                onChange={setHourInterval}
                options={HOURLY_INTERVALS.map((value) => ({
                  value,
                  label: t("everyHours", { count: Number(value) }),
                }))}
                className="w-[180px]"
              />
            </Field>
            <Field label={t("atMinute")}>
              <OptionSelect
                value={minute}
                onChange={setMinute}
                options={MINUTES.map((value) => ({
                  value,
                  label: `:${pad(value)}`,
                }))}
                className="w-[80px]"
              />
            </Field>
          </>
        )}

        {frequency === "weekly" && (
          <Field label={t("day")}>
            <OptionSelect
              value={dayOfWeek}
              onChange={setDayOfWeek}
              options={DAYS_OF_WEEK.map((value) => ({
                value,
                label: dayName(value),
              }))}
              className="w-[160px] capitalize"
            />
          </Field>
        )}

        {frequency === "monthly" && (
          <Field label={t("dayOfMonth")}>
            <OptionSelect
              value={dayOfMonth}
              onChange={setDayOfMonth}
              options={DAYS_OF_MONTH.map((value) => ({ value, label: value }))}
              className="w-[80px]"
            />
          </Field>
        )}

        {(frequency === "daily" ||
          frequency === "weekly" ||
          frequency === "monthly") &&
          timeField}

        {frequency === "custom" && (
          <div className="flex-1">
            <Field
              label={t("expression")}
              htmlFor={`cron_custom_expression${instanceId}`}
            >
              <Input
                id={`cron_custom_expression${instanceId}`}
                type="text"
                value={customExpr}
                onChange={(e) => setCustomExpr(e.target.value)}
                placeholder="0 9 * * 1-5"
                className="font-mono"
              />
              <p className="note">{t("expressionFields")}</p>
            </Field>
          </div>
        )}
      </div>

      <div className="flex items-center gap-2 rounded-md border border-border/70 bg-muted/40 px-3 py-2 text-xs text-muted-foreground">
        <span>{description}</span>
        {frequency !== "custom" && (
          <code className="ml-auto font-mono">{cronExpr}</code>
        )}
      </div>
    </div>
  );
}
