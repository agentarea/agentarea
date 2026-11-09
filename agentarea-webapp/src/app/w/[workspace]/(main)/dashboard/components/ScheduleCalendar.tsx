"use client";

import { useSyncExternalStore } from "react";
import { useLocale, useTranslations } from "next-intl";
import { CalendarDays, Repeat } from "lucide-react";
import { parseAsStringLiteral, useQueryState } from "nuqs";
import type { FrequentSchedule, Schedule, ScheduledRun } from "@/api/client";
import { BoardSectionHeader } from "@/components/board";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Skeleton } from "@/components/ui/skeleton";
import Link from "@/components/WorkspaceLink";
import {
  addDays,
  buildMonthWeeks,
  buildTodayAgenda,
  buildWeekDays,
  dayKey,
  firstRunFrom,
} from "./calendar";
import { DayGrid, UpcomingList } from "./DayGrid";
import { TimeGrid, type TimeGridFormats } from "./TimeGrid";

const VIEWS = ["today", "week", "month"] as const;
type View = (typeof VIEWS)[number];

const noopSubscribe = () => () => {};

/** Days are the viewer's local days, so the views render only in the browser. */
function useIsClient() {
  return useSyncExternalStore(
    noopSubscribe,
    () => true,
    () => false
  );
}

function FrequentChip({
  item,
  firstDate,
}: {
  item: FrequentSchedule;
  /** The day of the next run when it is not today. */
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

/** Schedules that fire through the day, above the hours like all-day events. */
function FrequentStrip({
  items,
  firstDate,
}: {
  items: FrequentSchedule[];
  firstDate: (item: FrequentSchedule) => string | null;
}) {
  const t = useTranslations("DashboardPage");
  if (items.length === 0) return null;
  return (
    <div className="flex shrink-0 items-center gap-1.5 overflow-x-auto border-b border-zinc-200 px-6 py-2.5 dark:border-zinc-700">
      <span className="mr-1 shrink-0 text-[11.5px] text-muted-foreground">
        {t("throughoutTheDay")}
      </span>
      {items.map((item) => (
        <FrequentChip
          key={item.trigger_id}
          item={item}
          firstDate={firstDate(item)}
        />
      ))}
    </div>
  );
}

/** What an empty view says: nothing here, and when the next run is. */
function EmptyNote({
  view,
  hasSchedule,
  next,
  formats,
}: {
  view: View;
  hasSchedule: boolean;
  next: ScheduledRun | FrequentSchedule | null;
  formats: TimeGridFormats;
}) {
  const t = useTranslations("DashboardPage");
  if (!hasSchedule) {
    return (
      <Link href="/triggers/create" className="hover:text-foreground">
        {t("nothingScheduled")}
      </Link>
    );
  }
  const nextAt =
    next && ("fires_at" in next ? next.fires_at : next.next_run_at);
  return (
    <>
      <div className="font-medium text-foreground">
        {t("nothingInView", { view })}
      </div>
      {next && nextAt && (
        <div className="mt-0.5">
          {t("nextRun", {
            title: next.title,
            when: `${formats.dayLabel(new Date(nextAt))} ${formats.time(nextAt)}`,
          })}
        </div>
      )}
    </>
  );
}

function ScheduleBody({
  view,
  schedule,
  formats,
}: {
  view: View;
  schedule: Schedule;
  formats: TimeGridFormats;
}) {
  const now = new Date();
  const hasSchedule = schedule.runs.length > 0 || schedule.frequent.length > 0;
  const laterFrequent = (item: FrequentSchedule) =>
    dayKey(new Date(item.next_run_at)) > dayKey(now)
      ? formats.dayLabel(new Date(item.next_run_at))
      : null;

  if (view === "today") {
    const agenda = buildTodayAgenda(schedule.runs, schedule.frequent, now);
    const empty = agenda.runs.length === 0 && agenda.frequent.length === 0;
    return (
      <>
        <FrequentStrip items={agenda.frequent} firstDate={() => null} />
        <TimeGrid
          runs={agenda.runs}
          formats={formats}
          note={
            empty ? (
              <EmptyNote
                view="today"
                hasSchedule={hasSchedule}
                next={agenda.next}
                formats={formats}
              />
            ) : null
          }
        />
      </>
    );
  }

  if (view === "week") {
    const days = buildWeekDays(schedule.runs, now);
    const note = (
      <EmptyNote
        view="week"
        hasSchedule={hasSchedule}
        next={firstRunFrom(
          schedule.runs,
          schedule.frequent,
          addDays(days[6].date, 1)
        )}
        formats={formats}
      />
    );
    return (
      <>
        <FrequentStrip items={schedule.frequent} firstDate={laterFrequent} />
        <div className="hidden min-h-0 flex-1 flex-col md:flex">
          <DayGrid
            weeks={[days]}
            maxChips={12}
            muteOutsideMonth={false}
            formats={formats}
          />
        </div>
        <div className="md:hidden">
          <UpcomingList days={days} formats={formats} empty={note} />
        </div>
      </>
    );
  }

  const weeks = buildMonthWeeks(schedule.runs, now);
  const note = (
    <EmptyNote
      view="month"
      hasSchedule={hasSchedule}
      next={null}
      formats={formats}
    />
  );
  return (
    <>
      <FrequentStrip items={schedule.frequent} firstDate={laterFrequent} />
      <div className="hidden min-h-0 flex-1 flex-col md:flex">
        <DayGrid
          weeks={weeks}
          maxChips={3}
          muteOutsideMonth
          formats={formats}
        />
      </div>
      <div className="md:hidden">
        <UpcomingList days={weeks.flat()} formats={formats} empty={note} />
      </div>
    </>
  );
}

export function ScheduleCalendar({ schedule }: { schedule: Schedule }) {
  const t = useTranslations("DashboardPage");
  const locale = useLocale();
  const isClient = useIsClient();
  const [view, setView] = useQueryState(
    "schedule",
    parseAsStringLiteral(VIEWS).withDefault("today")
  );

  const timeFmt = new Intl.DateTimeFormat(locale, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  });
  const weekdayFmt = new Intl.DateTimeFormat(locale, { weekday: "short" });
  const dayFmt = new Intl.DateTimeFormat(locale, {
    weekday: "short",
    day: "numeric",
    month: "short",
  });
  const formats: TimeGridFormats = {
    time: (iso) => timeFmt.format(new Date(iso)),
    hour: (h) => timeFmt.format(new Date(2000, 0, 1, h)),
    weekday: (d) => weekdayFmt.format(d),
    dayLabel: (d) => dayFmt.format(d),
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <div className="border-b border-zinc-200 px-6 pb-3 pt-4 dark:border-zinc-700">
        <BoardSectionHeader
          icon={<CalendarDays />}
          color="hsl(var(--foreground))"
          title={t("schedule")}
          meta={
            <SegmentedControl<View>
              layoutId="dashboard-schedule-view"
              value={view}
              onChange={(v) => void setView(v)}
              itemClassName="min-w-0 px-3"
              items={VIEWS.map((v) => ({
                value: v,
                label: t(`scheduleView.${v}`),
              }))}
            />
          }
        />
      </div>
      <div className="flex flex-col md:h-[500px] lg:h-auto lg:min-h-0 lg:flex-1">
        {isClient ? (
          <ScheduleBody view={view} schedule={schedule} formats={formats} />
        ) : (
          <Skeleton className="m-4 h-[460px] rounded-md md:h-auto md:flex-1" />
        )}
      </div>
    </div>
  );
}
