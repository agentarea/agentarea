"use client";

import { useState } from "react";
import {
  ArrowUpRight,
  CalendarDays,
  Check,
  Circle,
  Clock3,
  Repeat2,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { EntityIcon } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";
import {
  DEMO_NOW_ISO,
  DEMO_TIME_ZONE,
  formatConceptDay,
  formatConceptTime,
  isTaskBlocked,
  type ConceptTask,
  type ConceptViewProps,
} from "./concept-data";

const weekdayFormatter = new Intl.DateTimeFormat("en", {
  weekday: "short",
  timeZone: DEMO_TIME_ZONE,
});
const days = Array.from({ length: 7 }, (_, offset) => {
  const date = new Date(DEMO_NOW_ISO);
  date.setUTCDate(date.getUTCDate() + offset);
  return {
    key: date.toISOString().slice(0, 10),
    iso: date.toISOString(),
    weekday: weekdayFormatter.format(date),
    number: date.getUTCDate(),
  };
});

type ScheduledTask = ConceptTask & { scheduledAt: string };

export default function TimelineHypothesis({
  tasks,
  onOpenTask,
}: ConceptViewProps) {
  const [selectedDay, setSelectedDay] = useState<string | null>(null);
  const nowTasks = tasks.filter(
    (task) =>
      task.status === "running" || task.status === "waiting_for_approval"
  );
  const attentionCount = nowTasks.filter((task) => task.needsAttention).length;
  const scheduledTasks = tasks
    .filter(
      (task): task is ScheduledTask =>
        task.status === "scheduled" &&
        task.scheduledAt !== null &&
        task.scheduledAt >= DEMO_NOW_ISO
    )
    .sort((a, b) => a.scheduledAt.localeCompare(b.scheduledAt));
  const dayCounts = new Map<string, number>();
  const agenda = new Map<string, ScheduledTask[]>();
  for (const task of scheduledTasks) {
    const day = task.scheduledAt.slice(0, 10);
    dayCounts.set(day, (dayCounts.get(day) ?? 0) + 1);
    if (selectedDay !== null && selectedDay !== day) continue;
    const entries = agenda.get(day);
    if (entries) entries.push(task);
    else agenda.set(day, [task]);
  }
  const selectedDateLabel = selectedDay
    ? formatConceptDay(`${selectedDay}T00:00:00.000Z`)
    : "All upcoming";

  return (
    <div className="min-w-0 space-y-7">
      <section
        aria-label="Work happening now"
        className="overflow-hidden rounded-lg border border-border bg-muted/30"
      >
        <div className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-border px-4 py-3">
          <div className="flex items-center gap-2.5">
            <span
              aria-hidden="true"
              className="h-2 w-2 rounded-full bg-primary"
            />
            <h2 className="text-sm font-semibold">Now</h2>
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {formatConceptTime(DEMO_NOW_ISO)} {DEMO_TIME_ZONE}
            </span>
          </div>
          <span
            className={cn(
              "text-xs",
              attentionCount > 0
                ? "text-amber-800 dark:text-amber-300"
                : "text-muted-foreground"
            )}
          >
            {attentionCount > 0
              ? `${attentionCount} ${attentionCount === 1 ? "decision needs" : "decisions need"} you`
              : "No decisions waiting"}
          </span>
        </div>
        {nowTasks.length > 0 ? (
          <ul className="grid min-w-0 divide-y divide-border lg:grid-cols-3 lg:divide-x lg:divide-y-0">
            {nowTasks.map((task) => (
              <li key={task.id} className="min-w-0">
                <button
                  type="button"
                  onClick={(event) => onOpenTask(task.id, event.currentTarget)}
                  className="group flex h-full w-full min-w-0 items-start gap-3 px-4 py-3 text-left transition-colors hover:bg-muted/70 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-ring motion-reduce:transition-none"
                  aria-label={`Open ${task.goal}`}
                >
                  <span className="min-w-0 flex-1 space-y-1">
                    <span
                      className={cn(
                        "block text-[11px] font-medium",
                        task.needsAttention
                          ? "text-amber-800 dark:text-amber-300"
                          : "text-primary"
                      )}
                    >
                      {task.status === "waiting_for_approval"
                        ? "Awaiting approval · no scheduled time"
                        : "In progress"}
                    </span>
                    <span className="block text-sm font-medium leading-snug">
                      {task.goal}
                    </span>
                    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <span aria-hidden="true">
                        <EntityIcon kind="agent" className="h-3 w-3 shrink-0" />
                      </span>
                      <span className="min-w-0 break-words">{task.agent}</span>
                    </span>
                  </span>
                  <ArrowUpRight
                    aria-hidden="true"
                    className="mt-1 h-3.5 w-3.5 shrink-0 text-muted-foreground transition-colors group-hover:text-foreground"
                  />
                </button>
              </li>
            ))}
          </ul>
        ) : (
          <p className="px-4 py-3 text-sm text-muted-foreground">
            No work in progress.
          </p>
        )}
      </section>

      <section aria-label="Upcoming agenda" className="min-w-0">
        <div className="mb-3 flex flex-wrap items-center justify-between gap-3">
          <div className="flex items-baseline gap-2">
            <h2 className="text-base font-semibold tracking-tight">
              September 2026
            </h2>
            <span className="text-xs text-muted-foreground">
              {DEMO_TIME_ZONE}
            </span>
          </div>
          <Button
            type="button"
            variant={selectedDay === null ? "secondary" : "ghost"}
            size="sm"
            aria-pressed={selectedDay === null}
            onClick={() => setSelectedDay(null)}
          >
            All upcoming
          </Button>
        </div>
        <div
          role="group"
          aria-label="Filter agenda by day"
          className="grid grid-cols-7 gap-1 rounded-lg border border-border bg-muted/20 p-1 sm:gap-2 sm:p-2"
        >
          {days.map((day) => {
            const count = dayCounts.get(day.key) ?? 0;
            const selected = selectedDay === day.key;
            return (
              <button
                key={day.key}
                type="button"
                aria-pressed={selected}
                aria-label={`${formatConceptDay(day.iso)}, ${count} scheduled ${count === 1 ? "entry" : "entries"}`}
                onClick={() => setSelectedDay(day.key)}
                className={cn(
                  "flex min-w-0 flex-col items-center gap-1 rounded-md px-1 py-2.5 transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-reduce:transition-none",
                  selected
                    ? "bg-primary text-primary-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <span className="text-[10px] sm:text-xs">{day.weekday}</span>
                <span
                  className={cn(
                    "font-mono text-lg font-medium tabular-nums sm:text-xl",
                    !selected && "text-foreground"
                  )}
                >
                  {day.number}
                </span>
                <span aria-hidden="true" className="text-[10px] tabular-nums">
                  {count > 0
                    ? `${count} ${count === 1 ? "entry" : "entries"}`
                    : "—"}
                </span>
              </button>
            );
          })}
        </div>

        <div
          role="status"
          className="my-5 flex flex-wrap items-center justify-between gap-2 text-xs text-muted-foreground"
        >
          <span>{selectedDateLabel}</span>
          <span className="flex items-center gap-1.5">
            <Clock3 aria-hidden="true" className="h-3.5 w-3.5" />
            Scheduled start times, not durations
          </span>
        </div>

        {agenda.size > 0 ? (
          <div className="min-w-0">
            {Array.from(agenda, ([day, entries]) => (
              <section
                key={day}
                aria-label={formatConceptDay(entries[0].scheduledAt)}
                className="grid min-w-0 gap-3 sm:grid-cols-[112px_minmax(0,1fr)] sm:gap-6"
              >
                <h3 className="flex items-baseline gap-2 pb-1 pt-1 text-sm font-semibold sm:block sm:pt-4">
                  {formatConceptDay(entries[0].scheduledAt)}
                  {day === days[0].key ? (
                    <span className="text-xs font-normal text-primary sm:mt-1 sm:block">
                      Today
                    </span>
                  ) : null}
                </h3>
                <ol className="ml-1 min-w-0 border-l border-border pb-6 pl-4 sm:pl-6">
                  {entries.map((task) => {
                    const blocked = isTaskBlocked(task, tasks);
                    const pendingDependencies = tasks.filter(
                      (dependency) =>
                        task.dependsOn.includes(dependency.id) &&
                        dependency.status !== "completed"
                    );
                    const projected =
                      task.scheduleKind === "recurring-occurrence";
                    return (
                      <li
                        key={task.id}
                        className="relative min-w-0 border-b border-border last:border-b-0"
                      >
                        <span
                          aria-hidden="true"
                          className={cn(
                            "absolute -left-[21px] top-6 h-2 w-2 rounded-full border-2 border-background ring-1 ring-border sm:-left-[29px]",
                            projected ? "bg-background" : "bg-primary"
                          )}
                        />
                        <button
                          type="button"
                          onClick={(event) =>
                            onOpenTask(task.id, event.currentTarget)
                          }
                          aria-label={`Open ${projected ? "projected occurrence: " : ""}${task.goal}`}
                          className="group grid w-full min-w-0 grid-cols-[44px_minmax(0,1fr)] gap-3 rounded-md py-4 text-left transition-colors hover:bg-muted/40 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:grid-cols-[56px_minmax(0,1fr)] sm:gap-4 motion-reduce:transition-none"
                        >
                          <time
                            dateTime={task.scheduledAt}
                            className="pt-0.5 font-mono text-xs font-medium tabular-nums text-muted-foreground sm:text-sm"
                          >
                            {formatConceptTime(task.scheduledAt)}
                          </time>
                          <span className="min-w-0 space-y-2">
                            <span className="flex items-start gap-2">
                              <span className="min-w-0 flex-1 text-sm font-semibold leading-snug sm:text-base">
                                {task.goal}
                              </span>
                              <ArrowUpRight
                                aria-hidden="true"
                                className="mr-1 mt-0.5 h-4 w-4 shrink-0 text-muted-foreground group-hover:text-foreground"
                              />
                            </span>
                            <span className="flex flex-wrap items-center gap-x-4 gap-y-1.5 text-xs text-muted-foreground">
                              <span className="inline-flex min-w-0 items-center gap-1.5">
                                <span aria-hidden="true">
                                  <EntityIcon
                                    kind="agent"
                                    className="h-3.5 w-3.5"
                                  />
                                </span>
                                <span className="min-w-0 break-words">
                                  {task.agent}
                                </span>
                              </span>
                              <span className="inline-flex min-w-0 items-center gap-1.5">
                                <span aria-hidden="true">
                                  <EntityIcon
                                    kind="project"
                                    className="h-3.5 w-3.5"
                                  />
                                </span>
                                <span className="min-w-0 break-words">
                                  {task.project}
                                </span>
                              </span>
                            </span>
                            <span className="flex flex-wrap items-center gap-x-3 gap-y-1.5 text-[11px]">
                              <span className="inline-flex items-center gap-1 text-muted-foreground">
                                {projected ? (
                                  <Repeat2
                                    aria-hidden="true"
                                    className="h-3 w-3"
                                  />
                                ) : (
                                  <CalendarDays
                                    aria-hidden="true"
                                    className="h-3 w-3"
                                  />
                                )}
                                {projected
                                  ? "Projected recurring occurrence · not created"
                                  : "Scheduled task"}
                              </span>
                              <span
                                className={cn(
                                  "inline-flex items-start gap-1",
                                  blocked
                                    ? "text-amber-800 dark:text-amber-300"
                                    : "text-emerald-700 dark:text-emerald-400"
                                )}
                              >
                                {blocked ? (
                                  <Circle
                                    aria-hidden="true"
                                    className="mt-0.5 h-3 w-3 shrink-0"
                                  />
                                ) : (
                                  <Check
                                    aria-hidden="true"
                                    className="mt-0.5 h-3 w-3 shrink-0"
                                  />
                                )}
                                <span>
                                  {blocked
                                    ? `Waiting on ${pendingDependencies.map((dependency) => dependency.goal).join("; ") || "a prerequisite"}`
                                    : "Ready at scheduled time"}
                                </span>
                              </span>
                            </span>
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ol>
              </section>
            ))}
          </div>
        ) : (
          <div className="rounded-lg border border-dashed border-border px-5 py-10 text-center">
            <CalendarDays
              aria-hidden="true"
              className="mx-auto mb-3 h-5 w-5 text-muted-foreground"
            />
            <h3 className="text-sm font-medium">
              {selectedDay
                ? `Nothing scheduled for ${selectedDateLabel}`
                : "No upcoming scheduled work"}
            </h3>
            <p className="mt-2 text-xs text-muted-foreground">
              Ongoing work and approvals remain in Now above.
            </p>
            {selectedDay ? (
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="mt-4"
                onClick={() => setSelectedDay(null)}
              >
                Show all upcoming
              </Button>
            ) : null}
          </div>
        )}
      </section>
    </div>
  );
}
