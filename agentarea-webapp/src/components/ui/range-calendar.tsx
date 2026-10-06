"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import {
  addDays,
  addMonths,
  endOfMonth,
  endOfWeek,
  format,
  isAfter,
  isBefore,
  isSameDay,
  isSameMonth,
  isToday,
  startOfMonth,
  startOfWeek,
  type Locale,
} from "date-fns";
import { enUS, ru } from "date-fns/locale";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";

const LOCALES: Record<string, Locale> = { en: enUS, ru };

export interface RangeCalendarProps {
  /** First day of the range shown; with no `to`, a range still being picked. */
  from?: Date;
  /** Last day of the range shown. */
  to?: Date;
  /** A day was clicked. */
  onPick: (day: Date) => void;
  /** Days after this one cannot be picked, e.g. today for a log. */
  max?: Date;
}

/**
 * One month of days to pick a date range on: the caller decides what a click
 * means. While only `from` is set, hovering previews the range it would make.
 * Month and weekday names, and the first day of the week, follow the UI locale.
 */
export function RangeCalendar({ from, to, onPick, max }: RangeCalendarProps) {
  const t = useTranslations("Common");
  const locale = LOCALES[useLocale()] ?? enUS;
  const [month, setMonth] = useState(() =>
    startOfMonth(to ?? from ?? new Date())
  );
  const [hovered, setHovered] = useState<Date | null>(null);

  const first = startOfWeek(startOfMonth(month), { locale });
  const last = endOfWeek(endOfMonth(month), { locale });
  const days: Date[] = [];
  for (let day = first; !isAfter(day, last); day = addDays(day, 1)) {
    days.push(day);
  }

  // While picking, the range runs from the first click to the hovered day.
  const end = to ?? (from && hovered ? hovered : undefined);
  const [start, stop] =
    from && end && isBefore(end, from) ? [end, from] : [from, end];
  const title = format(month, "LLLL yyyy", { locale });
  const canGoForward = !max || isBefore(endOfMonth(month), max);

  return (
    <div
      className="w-[15.5rem] select-none"
      onMouseLeave={() => setHovered(null)}
    >
      <div className="mb-2 flex items-center justify-between">
        <button
          type="button"
          aria-label={t("previousMonth")}
          onClick={() => setMonth((m) => addMonths(m, -1))}
          className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground"
        >
          <ChevronLeft className="h-4 w-4" />
        </button>
        <span className="text-[13px] font-medium">
          {title.charAt(0).toUpperCase() + title.slice(1)}
        </span>
        <button
          type="button"
          aria-label={t("nextMonth")}
          disabled={!canGoForward}
          onClick={() => setMonth((m) => addMonths(m, 1))}
          className="grid h-7 w-7 place-items-center rounded-md text-muted-foreground hover:bg-muted hover:text-foreground disabled:pointer-events-none disabled:opacity-40"
        >
          <ChevronRight className="h-4 w-4" />
        </button>
      </div>

      <div className="grid grid-cols-7 gap-y-0.5 text-center">
        {days.slice(0, 7).map((day) => (
          <span
            key={`weekday-${day.getDay()}`}
            className="pb-1 text-[11px] font-medium capitalize text-muted-foreground"
          >
            {format(day, "EEEEEE", { locale })}
          </span>
        ))}

        {days.map((day, index) => {
          const disabled = Boolean(max && isAfter(day, max));
          const isStart = Boolean(start && isSameDay(day, start));
          const isStop = Boolean(stop && isSameDay(day, stop));
          const inRange = Boolean(
            start && stop && isAfter(day, start) && isBefore(day, stop)
          );
          const outside = !isSameMonth(day, month);
          const banded =
            inRange ||
            (isStart && stop && !isStop) ||
            (isStop && start && !isStart);

          return (
            <div
              key={day.toISOString()}
              className={cn(
                "flex h-8 items-center justify-center",
                banded && "bg-primary/10",
                // The band breaks at the week's edges and at its own ends.
                banded &&
                  (index % 7 === 0 || (isStart && !isStop)) &&
                  "rounded-l-md",
                banded &&
                  (index % 7 === 6 || (isStop && !isStart)) &&
                  "rounded-r-md"
              )}
            >
              <button
                type="button"
                disabled={disabled}
                aria-pressed={isStart || isStop}
                aria-label={format(day, "PPP", { locale })}
                onClick={() => onPick(day)}
                onMouseEnter={() => setHovered(day)}
                className={cn(
                  "h-8 w-8 rounded-md text-[12.5px] tabular-nums transition-colors",
                  isStart || isStop
                    ? "bg-primary font-medium text-primary-foreground"
                    : "hover:bg-muted",
                  outside && !isStart && !isStop && "text-muted-foreground/50",
                  isToday(day) &&
                    !isStart &&
                    !isStop &&
                    "font-semibold text-primary",
                  disabled && "pointer-events-none opacity-30"
                )}
              >
                {format(day, "d")}
              </button>
            </div>
          );
        })}
      </div>
    </div>
  );
}
