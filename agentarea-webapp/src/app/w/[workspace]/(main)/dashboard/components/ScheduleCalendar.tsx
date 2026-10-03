"use client";

import { useSyncExternalStore } from "react";
import { useLocale, useTranslations } from "next-intl";
import { CalendarDays, Repeat } from "lucide-react";
import type { FrequentSchedule, Schedule, ScheduledRun } from "@/api/client";
import { AgentAvatar } from "@/components/AgentAvatar";
import { BoardSectionHeader } from "@/components/board";
import { Skeleton } from "@/components/ui/skeleton";
import Link from "@/components/WorkspaceLink";
import { cn } from "@/lib/utils";
import { buildCalendarWeeks, dayKey, type CalendarDay } from "./calendar";

const MAX_CHIPS_PER_DAY = 2;

const noopSubscribe = () => () => {};

/** Days are the viewer's local days, so the grid renders only in the browser. */
function useIsClient() {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  );
}

function RunChip({
  run,
  time,
  date,
  withAgent = false,
}: {
  run: ScheduledRun;
  time: (iso: string) => string;
  /** The run's full date: the chip alone shows only the time. */
  date: string;
  /** The grid cell is too narrow for the avatar; the tooltip names the agent. */
  withAgent?: boolean;
}) {
  const name = run.agent_name ? `${run.title} · ${run.agent_name}` : run.title;
  return (
    <Link
      href={`/triggers/${run.trigger_id}`}
      className="flex min-w-0 items-center gap-1.5 rounded-md border border-zinc-200 bg-background px-1.5 py-0.5 text-[11.5px] leading-[18px] transition-colors hover:bg-muted dark:border-zinc-700"
      title={name}
      aria-label={`${date} ${time(run.fires_at)} ${name}`}
    >
      {withAgent && (
        <AgentAvatar
          agent={{ id: run.agent_id, name: run.agent_name ?? "" }}
          size="xs"
        />
      )}
      <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">
        {time(run.fires_at)}
      </span>
      <span className="min-w-0 truncate font-medium text-foreground">
        {run.title}
      </span>
    </Link>
  );
}

function FrequentChip({
  item,
  firstDate,
}: {
  item: FrequentSchedule;
  /** The day of the next run, in the viewer's zone; null until hydrated. */
  firstDate: string | null;
}) {
  const t = useTranslations("DashboardPage");
  const perDay = t("perDay", { count: item.runs_per_day });
  const from = firstDate ? t("fromDate", { date: firstDate }) : null;
  const name = item.agent_name
    ? `${item.title} · ${item.agent_name}`
    : item.title;
  return (
    <Link
      href={`/triggers/${item.trigger_id}`}
      className="flex min-w-0 items-center gap-1.5 rounded-md border border-dashed border-zinc-300 px-2 py-1 text-[11.5px] transition-colors hover:bg-muted dark:border-zinc-600"
      title={name}
      aria-label={[name, perDay, from].filter(Boolean).join(", ")}
    >
      <Repeat className="h-3 w-3 shrink-0 text-muted-foreground" />
      <span className="truncate font-medium text-foreground">{item.title}</span>
      <span className="shrink-0 font-mono text-muted-foreground">{perDay}</span>
      {from && <span className="shrink-0 text-muted-foreground">{from}</span>}
    </Link>
  );
}

function DayCell({
  day,
  time,
  dayLabel,
}: {
  day: CalendarDay<ScheduledRun>;
  time: (iso: string) => string;
  dayLabel: (d: Date) => string;
}) {
  const t = useTranslations("DashboardPage");
  const date = dayLabel(day.date);
  const shown = day.items.slice(0, MAX_CHIPS_PER_DAY);
  const hidden = day.items.length - shown.length;
  return (
    <div
      className={cn(
        "flex min-h-0 min-w-0 flex-col gap-1 overflow-hidden border-b border-r border-zinc-200 p-1.5 dark:border-zinc-700",
        day.isPast && "bg-muted/40"
      )}
    >
      <div className="flex items-center justify-between px-0.5">
        <span
          aria-hidden
          className={cn(
            "inline-flex h-5 min-w-5 items-center justify-center rounded-full px-1 text-[12px] font-semibold tabular-nums",
            day.isToday && "bg-foreground text-background",
            day.isPast && "text-muted-foreground"
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
        <RunChip
          key={`${run.trigger_id}-${run.fires_at}`}
          run={run}
          time={time}
          date={date}
        />
      ))}
      {hidden > 0 && (
        <span className="px-1 text-[11px] text-muted-foreground">
          {t("moreRuns", { count: hidden })}
        </span>
      )}
    </div>
  );
}

export function ScheduleCalendar({ schedule }: { schedule: Schedule }) {
  const t = useTranslations("DashboardPage");
  const locale = useLocale();
  const isClient = useIsClient();

  const timeFmt = new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const time = (iso: string) => timeFmt.format(new Date(iso));
  const weekdayFmt = new Intl.DateTimeFormat(locale, { weekday: "short" });
  const dayFmt = new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });

  const isEmpty = schedule.runs.length === 0 && schedule.frequent.length === 0;

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-zinc-200 px-6 pb-3 pt-4 dark:border-zinc-700">
        <BoardSectionHeader
          icon={<CalendarDays />}
          color="hsl(var(--foreground))"
          title={t("schedule")}
          meta={
            isEmpty ? (
              <Link href="/triggers/create" className="hover:text-foreground">
                {t("nothingScheduled")}
              </Link>
            ) : (
              t("scheduleMeta", { days: schedule.horizon_days })
            )
          }
        />
        {schedule.frequent.length > 0 && (
          <div className="mt-3 flex flex-wrap items-center gap-1.5">
            <span className="mr-1 text-[11.5px] text-muted-foreground">
              {t("throughoutTheDay")}
            </span>
            {schedule.frequent.map((item) => (
              <FrequentChip
                key={item.trigger_id}
                item={item}
                firstDate={
                  isClient ? dayFmt.format(new Date(item.next_run_at)) : null
                }
              />
            ))}
          </div>
        )}
      </div>

      {!isClient ? (
        <Skeleton className="m-4 flex-1 rounded-md" />
      ) : (
        <CalendarBody
          schedule={schedule}
          time={time}
          weekday={(d) => weekdayFmt.format(d)}
          dayLabel={(d) => dayFmt.format(d)}
        />
      )}
    </div>
  );
}

function CalendarBody({
  schedule,
  time,
  weekday,
  dayLabel,
}: {
  schedule: Schedule;
  time: (iso: string) => string;
  weekday: (d: Date) => string;
  dayLabel: (d: Date) => string;
}) {
  const weeks = buildCalendarWeeks(
    schedule.runs,
    new Date(),
    schedule.horizon_days
  );
  const upcomingDays = weeks
    .flat()
    .filter((d) => !d.isPast && d.items.length > 0);

  return (
    <>
      <div className="hidden min-h-0 flex-1 flex-col overflow-y-auto md:flex">
        <div className="grid grid-cols-7 border-b border-zinc-200 dark:border-zinc-700">
          {weeks[0].map((d) => (
            <div
              key={dayKey(d.date)}
              className="px-2 py-1.5 text-[11.5px] font-medium capitalize text-muted-foreground"
            >
              {weekday(d.date)}
            </div>
          ))}
        </div>
        <div
          className="grid min-h-0 flex-1 grid-cols-7"
          style={{
            gridTemplateRows: `repeat(${weeks.length}, minmax(96px, 1fr))`,
          }}
        >
          {weeks.flat().map((day) => (
            <DayCell
              key={dayKey(day.date)}
              day={day}
              time={time}
              dayLabel={dayLabel}
            />
          ))}
        </div>
      </div>

      <div className="md:hidden">
        {upcomingDays.map((day) => (
          <div
            key={dayKey(day.date)}
            className="border-b border-zinc-200 px-6 py-2.5 dark:border-zinc-700"
          >
            <div className="mb-1.5 text-[12px] font-medium capitalize text-muted-foreground">
              {dayLabel(day.date)}
            </div>
            <div className="flex flex-col gap-1">
              {day.items.map((run) => (
                <RunChip
                  key={`${run.trigger_id}-${run.fires_at}`}
                  run={run}
                  time={time}
                  date={dayLabel(day.date)}
                  withAgent
                />
              ))}
            </div>
          </div>
        ))}
      </div>
    </>
  );
}
