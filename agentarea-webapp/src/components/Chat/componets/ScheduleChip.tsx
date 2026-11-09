"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { isBefore, isSameDay, isToday } from "date-fns";
import {
  CalendarClock,
  CalendarDays,
  Clock,
  Hourglass,
  Sunrise,
  Zap,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { MenuRow } from "@/components/ui/menu-row";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  RangeCalendar,
  useCalendarLocale,
} from "@/components/ui/range-calendar";
import { cn } from "@/lib/utils";
import {
  atClock,
  defaultScheduleTime,
  earliestScheduleTime,
  formatScheduleClock,
  formatScheduleDay,
  parseScheduleClock,
  parseScheduleDay,
  schedulePresets,
  type SchedulePreset,
} from "../utils/scheduleTime";

const ICON = "h-3.5 w-3.5";

const PRESET_ICONS: Record<SchedulePreset, typeof Clock> = {
  inOneHour: Hourglass,
  tomorrowMorning: Sunrise,
  mondayMorning: CalendarDays,
};

interface ScheduleChipProps {
  /** Null runs the task as soon as it is sent. */
  value: Date | null;
  onChange: (value: Date | null) => void;
  disabled?: boolean;
  /** Opened from outside, e.g. the composer's add menu; uncontrolled when absent. */
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
}

export function ScheduleChip({
  value,
  onChange,
  disabled,
  open: openProp,
  onOpenChange,
}: ScheduleChipProps) {
  const t = useTranslations("Chat.inputControls");
  const locale = useLocale();
  const calendarLocale = useCalendarLocale();
  const [openState, setOpenState] = useState(false);
  const open = openProp ?? openState;
  const setOpen = (next: boolean) => {
    setOpenState(next);
    onOpenChange?.(next);
  };
  // What the fields hold while typing; the value moves only on a whole time.
  const [dayText, setDayText] = useState("");
  const [clockText, setClockText] = useState("");
  const [error, setError] = useState<string | null>(null);

  const label = value
    ? new Intl.DateTimeFormat(locale, {
        day: "numeric",
        month: "short",
        hour: "2-digit",
        minute: "2-digit",
        hourCycle: "h23",
      }).format(value)
    : t("runNow");

  const showInFields = (date: Date | null) => {
    setDayText(date ? formatScheduleDay(date, calendarLocale) : "");
    setClockText(date ? formatScheduleClock(date) : "");
    setError(null);
  };

  const toggle = (next: boolean) => {
    if (next) showInFields(value);
    setOpen(next);
  };

  const choose = (date: Date | null) => {
    onChange(date);
    showInFields(date);
  };

  // A typed day and time become the value once both read and are ahead.
  const commitTyped = (day: string, clock: string): boolean => {
    if (!day.trim() && !clock.trim()) {
      onChange(null);
      setError(null);
      return true;
    }
    const pickedDay = parseScheduleDay(day, calendarLocale);
    const pickedClock = parseScheduleClock(clock);
    if (!pickedDay || !pickedClock) {
      setError(
        t("invalidTime", {
          example: `${formatScheduleDay(new Date(), calendarLocale)} 09:30`,
        })
      );
      return false;
    }
    const date = atClock(pickedDay, pickedClock);
    if (isBefore(date, earliestScheduleTime(new Date()))) {
      setError(t("timePassed"));
      return false;
    }
    choose(date);
    return true;
  };

  // Leaving a field half filled is still typing, not a mistake.
  const commitOnLeave = () => {
    if (dayText.trim() && clockText.trim()) commitTyped(dayText, clockText);
  };

  // A day from the calendar keeps the typed time, or takes the next free hour.
  const pickDay = (day: Date) => {
    const now = new Date();
    const clock = parseScheduleClock(clockText);
    let date = clock ? atClock(day, clock) : null;
    if (!date || isBefore(date, earliestScheduleTime(now))) {
      const fallback = defaultScheduleTime(now);
      date = isToday(day)
        ? fallback
        : atClock(day, {
            hours: fallback.getHours(),
            minutes: fallback.getMinutes(),
          });
    }
    choose(date);
  };

  const presets = schedulePresets(new Date());

  return (
    <Popover open={open} onOpenChange={toggle}>
      <PopoverTrigger asChild>
        <button
          type="button"
          disabled={disabled}
          aria-label={`${t("when")}: ${label}`}
          className={cn(
            "flex h-7 min-w-0 items-center gap-1 rounded-md px-1.5 text-[13px] leading-[1.2] transition-colors duration-150",
            "text-zinc-400 hover:bg-zinc-100/70 data-[state=open]:bg-zinc-100/80 dark:text-zinc-300 dark:hover:bg-zinc-800/80 dark:data-[state=open]:bg-zinc-800/80"
          )}
        >
          <CalendarClock
            aria-hidden
            className="h-3.5 w-3.5 shrink-0 text-zinc-400 dark:text-zinc-500"
          />
          <span className="truncate whitespace-nowrap pb-px">{label}</span>
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        collisionPadding={8}
        className="max-h-[var(--radix-popover-content-available-height)] w-auto max-w-[calc(100vw-1rem)] overflow-y-auto p-0"
        aria-label={t("runAt")}
      >
        <div className="flex flex-col sm:flex-row">
          {/* On a phone the presets sit two to a row so the calendar fits. */}
          <div className="grid grid-cols-2 p-1.5 max-sm:border-b sm:block sm:w-60 sm:border-r sm:border-border/60">
            <MenuRow
              icon={<Zap className={ICON} />}
              label={t("runNowAction")}
              selected={!value}
              onClick={() => {
                choose(null);
                setOpen(false);
              }}
            />
            {(Object.keys(presets) as SchedulePreset[]).map((preset) => {
              const Icon = PRESET_ICONS[preset];
              const date = presets[preset];
              return (
                <MenuRow
                  key={preset}
                  icon={<Icon className={ICON} />}
                  label={t(`presets.${preset}`)}
                  selected={Boolean(
                    value && value.getTime() === date.getTime()
                  )}
                  onClick={() => {
                    choose(date);
                    setOpen(false);
                  }}
                  trailing={
                    <span className="text-[11.5px] tabular-nums text-muted-foreground max-sm:hidden">
                      {formatScheduleClock(date)}
                    </span>
                  }
                />
              );
            })}
          </div>

          <form
            className="flex flex-col gap-2 p-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (commitTyped(dayText, clockText)) setOpen(false);
            }}
          >
            <div className="flex gap-2">
              <Input
                aria-label={t("date")}
                value={dayText}
                placeholder={formatScheduleDay(new Date(), calendarLocale)}
                leading={<CalendarDays className={ICON} />}
                className="h-8 text-[13px] tabular-nums"
                onChange={(event) => {
                  setDayText(event.target.value);
                  setError(null);
                }}
                onBlur={commitOnLeave}
              />
              <div className="w-[5.5rem] shrink-0">
                <Input
                  aria-label={t("time")}
                  value={clockText}
                  placeholder="09:30"
                  inputMode="numeric"
                  leading={<Clock className={ICON} />}
                  className="h-8 text-[13px] tabular-nums"
                  onChange={(event) => {
                    setClockText(event.target.value);
                    setError(null);
                  }}
                  onBlur={commitOnLeave}
                />
              </div>
            </div>
            {error ? (
              <p role="alert" className="text-xs text-destructive">
                {error}
              </p>
            ) : null}

            <RangeCalendar
              // The month follows a day picked outside the calendar.
              key={value ? `${value.getFullYear()}-${value.getMonth()}` : ""}
              from={value ?? undefined}
              to={value ?? undefined}
              min={new Date()}
              className="max-sm:w-full"
              onPick={(day) => {
                if (!value || !isSameDay(day, value)) pickDay(day);
              }}
            />

            <div className="flex justify-end pt-1">
              <Button type="submit" size="sm">
                {t("done")}
              </Button>
            </div>
          </form>
        </div>
      </PopoverContent>
    </Popover>
  );
}
