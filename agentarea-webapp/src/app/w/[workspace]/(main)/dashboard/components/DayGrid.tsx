import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import type { ScheduledRun } from "@/api/client";
import { cn } from "@/lib/utils";
import { dayKey, type CalendarDay } from "./calendar";
import { RunChip, runKey } from "./RunChip";
import type { TimeGridFormats } from "./TimeGrid";

function DayCell({
  day,
  maxChips,
  muteOutsideMonth,
  formats,
}: {
  day: CalendarDay<ScheduledRun>;
  maxChips: number;
  muteOutsideMonth: boolean;
  formats: TimeGridFormats;
}) {
  const t = useTranslations("DashboardPage");
  const date = formats.dayLabel(day.date);
  const shown = day.items.slice(0, maxChips);
  const hidden = day.items.length - shown.length;
  const muted = day.isPast || (muteOutsideMonth && !day.inMonth);
  return (
    <div
      className={cn(
        "flex min-h-0 min-w-0 flex-col gap-1 overflow-hidden border-b border-r border-zinc-200 p-1.5 dark:border-zinc-700",
        muted && "bg-muted/40"
      )}
    >
      <div className="flex items-center justify-between px-0.5">
        <span
          aria-hidden
          className={cn(
            "inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-[12px] font-semibold tabular-nums",
            day.isToday && "bg-foreground text-background",
            !day.isToday && muted && "text-muted-foreground"
          )}
        >
          {day.date.getDate()}
        </span>
        <span className="sr-only">{date}</span>
        {day.items.length > 0 && (
          <span className="text-[11px] tabular-nums text-muted-foreground">
            <span aria-hidden>{day.items.length}</span>
            <span className="sr-only">
              {t("runCount", { count: day.items.length })}
            </span>
          </span>
        )}
      </div>
      {shown.map((run) => (
        <RunChip key={runKey(run)} run={run} time={formats.time} date={date} />
      ))}
      {hidden > 0 && (
        <span className="px-1 text-[11px] text-muted-foreground">
          {t("moreRuns", { count: hidden })}
        </span>
      )}
    </div>
  );
}

/** Weeks as a 7-column day grid: the week view is one row, the month view several. */
export function DayGrid({
  weeks,
  maxChips,
  muteOutsideMonth,
  formats,
}: {
  weeks: CalendarDay<ScheduledRun>[][];
  maxChips: number;
  muteOutsideMonth: boolean;
  formats: TimeGridFormats;
}) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="grid shrink-0 grid-cols-7 border-b border-zinc-200 dark:border-zinc-700">
        {weeks[0].map((d) => (
          <div
            key={dayKey(d.date)}
            className="px-2 py-1.5 text-[11.5px] font-medium capitalize text-muted-foreground"
          >
            {formats.weekday(d.date)}
          </div>
        ))}
      </div>
      <div
        className="grid min-h-0 flex-1 grid-cols-7"
        style={{ gridTemplateRows: `repeat(${weeks.length}, minmax(0, 1fr))` }}
      >
        {weeks.flat().map((day) => (
          <DayCell
            key={dayKey(day.date)}
            day={day}
            maxChips={maxChips}
            muteOutsideMonth={muteOutsideMonth}
            formats={formats}
          />
        ))}
      </div>
    </div>
  );
}

/** A phone's week and month: the days ahead that have runs. */
export function UpcomingList({
  days,
  formats,
  empty,
}: {
  days: CalendarDay<ScheduledRun>[];
  formats: TimeGridFormats;
  empty: ReactNode;
}) {
  const upcoming = days.filter((d) => !d.isPast && d.items.length > 0);
  if (upcoming.length === 0) {
    return (
      <div className="px-6 py-6 text-[13px] text-muted-foreground">{empty}</div>
    );
  }
  return (
    <>
      {upcoming.map((day) => (
        <div
          key={dayKey(day.date)}
          className="border-b border-zinc-200 px-6 py-2.5 dark:border-zinc-700"
        >
          <div className="mb-1.5 text-[12px] font-medium capitalize text-muted-foreground">
            {formats.dayLabel(day.date)}
          </div>
          <div className="flex flex-col gap-1">
            {day.items.map((run) => (
              <RunChip
                key={runKey(run)}
                run={run}
                time={formats.time}
                date={formats.dayLabel(day.date)}
                withAgent
              />
            ))}
          </div>
        </div>
      ))}
    </>
  );
}
