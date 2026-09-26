"use client";

import { useState } from "react";
import {
  ArrowUpRight,
  Check,
  CheckCircle2,
  ChevronDown,
  Clock3,
  LockKeyhole,
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
  type ConceptWorkstream,
} from "./concept-data";

type AssignmentProps = {
  assignment: ConceptWorkstream;
  tasks: readonly ConceptTask[];
  onOpenTask: (id: string, opener: HTMLElement) => void;
};

function orderContributions(steps: readonly ConceptTask[]) {
  const byId = new Map(steps.map((task) => [task.id, task]));
  const visited = new Set<string>();
  const ordered: ConceptTask[] = [];

  function visit(task: ConceptTask) {
    if (visited.has(task.id)) return;
    visited.add(task.id);
    for (const dependencyId of task.dependsOn) {
      const dependency = byId.get(dependencyId);
      if (dependency) visit(dependency);
    }
    ordered.push(task);
  }

  steps.forEach(visit);
  return ordered;
}

function dependencyMessage(
  task: ConceptTask,
  tasksById: ReadonlyMap<string, ConceptTask>
) {
  if (task.dependsOn.length === 0) return null;

  const unresolved = task.dependsOn
    .map((id) => tasksById.get(id))
    .filter((dependency): dependency is ConceptTask =>
      Boolean(dependency && dependency.status !== "completed")
    );

  if (unresolved.length === 0) {
    return "Prerequisites complete · waiting for scheduled time";
  }

  return `Waiting on ${unresolved.map((dependency) => dependency.goal).join("; ")}`;
}

function OngoingAssignment({ assignment, tasks, onOpenTask }: AssignmentProps) {
  const [showAllScheduled, setShowAllScheduled] = useState(false);
  const assignmentTasks = tasks.filter(
    (task) => task.workstreamId === assignment.id
  );
  const tasksById = new Map(tasks.map((task) => [task.id, task]));
  const runningTasks = assignmentTasks.filter(
    (task) => task.status === "running"
  );
  const scheduledTasks = assignmentTasks
    .filter(
      (task): task is ConceptTask & { scheduledAt: string } =>
        task.status === "scheduled" &&
        task.scheduledAt !== null &&
        task.scheduledAt >= DEMO_NOW_ISO
    )
    .sort((first, second) =>
      first.scheduledAt.localeCompare(second.scheduledAt)
    );
  const completedTasks = assignmentTasks.filter(
    (task) => task.status === "completed"
  );
  const visibleScheduledTasks = showAllScheduled
    ? scheduledTasks
    : scheduledTasks.slice(0, 1);

  return (
    <section
      aria-labelledby={`assignment-${assignment.id}`}
      className="min-w-0 overflow-hidden rounded-xl border border-border bg-card"
    >
      <div className="border-b border-border bg-muted/25 p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Ongoing
          </span>
          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-700 dark:text-emerald-400">
            <span
              aria-hidden="true"
              className="h-1.5 w-1.5 rounded-full bg-current"
            />
            Active assignment
          </span>
        </div>
        <h2
          id={`assignment-${assignment.id}`}
          className="mt-4 text-xl font-semibold leading-tight tracking-tight sm:text-2xl"
        >
          {assignment.title}
        </h2>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          {assignment.brief}
        </p>
        <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
          <EntityIcon
            kind="agent"
            aria-hidden="true"
            className="h-3.5 w-3.5 shrink-0"
          />
          <span>
            Responsible agent ·{" "}
            <span className="font-medium text-foreground">
              {assignment.owner}
            </span>
          </span>
        </div>
        {assignment.workingAgreement ? (
          <div className="mt-5 rounded-lg border border-border bg-background/70 p-3.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Working agreement
            </p>
            <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
              {assignment.workingAgreement}
            </p>
          </div>
        ) : null}
      </div>

      <div className="space-y-6 p-5 sm:p-6">
        <section aria-labelledby={`assignment-${assignment.id}-now`}>
          <h3
            id={`assignment-${assignment.id}-now`}
            className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
          >
            Work right now
          </h3>
          {runningTasks.length > 0 ? (
            <ul className="mt-2 divide-y divide-border">
              {runningTasks.map((task) => (
                <li key={task.id}>
                  <button
                    type="button"
                    onClick={(event) =>
                      onOpenTask(task.id, event.currentTarget)
                    }
                    className="group flex w-full min-w-0 items-start gap-3 rounded-md py-3 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                  >
                    <span
                      aria-hidden="true"
                      className="mt-1.5 h-2 w-2 shrink-0 rounded-full bg-primary"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">
                        {task.goal}
                      </span>
                      <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                        {task.activity}
                      </span>
                    </span>
                    <ArrowUpRight
                      aria-hidden="true"
                      className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground group-hover:text-foreground"
                    />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="mt-2 rounded-lg border border-dashed border-border px-4 py-3">
              <p className="text-sm font-medium">No task running</p>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">
                The responsibility stays active between scheduled checks and
                reviewed changes.
              </p>
            </div>
          )}
        </section>

        <section aria-labelledby={`assignment-${assignment.id}-scheduled`}>
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h3
              id={`assignment-${assignment.id}-scheduled`}
              className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
            >
              Scheduled work
            </h3>
            <span className="font-mono text-[11px] text-muted-foreground">
              {DEMO_TIME_ZONE}
            </span>
          </div>
          {visibleScheduledTasks.length > 0 ? (
            <ol
              id={`assignment-${assignment.id}-scheduled-list`}
              className="mt-2 divide-y divide-border"
            >
              {visibleScheduledTasks.map((task) => {
                const blocked = isTaskBlocked(task, tasks);
                const dependency = dependencyMessage(task, tasksById);
                const projected = task.scheduleKind === "recurring-occurrence";

                return (
                  <li key={task.id}>
                    <button
                      type="button"
                      onClick={(event) =>
                        onOpenTask(task.id, event.currentTarget)
                      }
                      className="group flex w-full min-w-0 items-start gap-3 rounded-md py-3 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                    >
                      <Clock3
                        aria-hidden="true"
                        className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                      />
                      <span className="min-w-0 flex-1">
                        <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                          <time
                            dateTime={task.scheduledAt}
                            className="font-mono text-xs font-medium tabular-nums"
                          >
                            {formatConceptDay(task.scheduledAt)} ·{" "}
                            {formatConceptTime(task.scheduledAt)}
                          </time>
                          {projected ? (
                            <span className="inline-flex items-center gap-1 text-[10px] text-muted-foreground">
                              <Repeat2 aria-hidden="true" className="h-3 w-3" />
                              Projected occurrence · not created
                            </span>
                          ) : null}
                        </span>
                        <span className="mt-1 block text-sm font-medium">
                          {task.goal}
                        </span>
                        <span
                          className={cn(
                            "mt-1 block text-xs leading-5",
                            blocked
                              ? "text-amber-700 dark:text-amber-300"
                              : "text-muted-foreground"
                          )}
                        >
                          {dependency ??
                            (projected
                              ? "Waiting for this recurring time"
                              : "Waiting for scheduled time")}
                        </span>
                      </span>
                      <ArrowUpRight
                        aria-hidden="true"
                        className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground group-hover:text-foreground"
                      />
                    </button>
                  </li>
                );
              })}
            </ol>
          ) : (
            <p className="mt-2 text-sm leading-6 text-muted-foreground">
              No scheduled work. Event-driven work will appear when its trigger
              occurs.
            </p>
          )}
          {scheduledTasks.length > 1 ? (
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="mt-2 -ml-3"
              aria-expanded={showAllScheduled}
              aria-controls={`assignment-${assignment.id}-scheduled-list`}
              onClick={() => setShowAllScheduled((current) => !current)}
            >
              <ChevronDown
                aria-hidden="true"
                className={cn(
                  "transition-transform motion-reduce:transition-none",
                  showAllScheduled && "rotate-180"
                )}
              />
              {showAllScheduled
                ? "Show next only"
                : `Show all ${scheduledTasks.length} scheduled tasks`}
            </Button>
          ) : null}
        </section>

        <section aria-labelledby={`assignment-${assignment.id}-recent`}>
          <h3
            id={`assignment-${assignment.id}-recent`}
            className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground"
          >
            Recent completed work
          </h3>
          {completedTasks.length > 0 ? (
            <ul className="mt-2 divide-y divide-border">
              {completedTasks.map((task) => (
                <li key={task.id}>
                  <button
                    type="button"
                    onClick={(event) =>
                      onOpenTask(task.id, event.currentTarget)
                    }
                    className="group flex w-full min-w-0 items-start gap-3 rounded-md py-3 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                  >
                    <CheckCircle2
                      aria-hidden="true"
                      className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700 dark:text-emerald-400"
                    />
                    <span className="min-w-0 flex-1">
                      <span className="block text-sm font-medium">
                        {task.goal}
                      </span>
                      <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                        {task.outcome?.label ?? task.activity}
                      </span>
                    </span>
                    <ArrowUpRight
                      aria-hidden="true"
                      className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground group-hover:text-foreground"
                    />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-muted-foreground">
              No completed work recorded yet.
            </p>
          )}
        </section>
      </div>
    </section>
  );
}

function OneOffAssignment({ assignment, tasks, onOpenTask }: AssignmentProps) {
  const assignmentTasks = orderContributions(
    tasks.filter((task) => task.workstreamId === assignment.id)
  );
  const tasksById = new Map(tasks.map((task) => [task.id, task]));
  const completedCount = assignmentTasks.filter(
    (task) => task.status === "completed"
  ).length;
  const complete =
    assignmentTasks.length > 0 && completedCount === assignmentTasks.length;
  const needsAcceptance = assignmentTasks.some(
    (task) => task.status === "waiting_for_approval" && task.needsAttention
  );

  return (
    <section
      aria-labelledby={`assignment-${assignment.id}`}
      className="min-w-0 overflow-hidden rounded-xl border border-border bg-card"
    >
      <div className="border-b border-border bg-muted/25 p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <span className="rounded-full border border-border bg-background px-2.5 py-1 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            One-off
          </span>
          <span
            className={cn(
              "inline-flex items-center gap-1.5 text-xs font-medium",
              complete
                ? "text-emerald-700 dark:text-emerald-400"
                : needsAcceptance
                  ? "text-amber-700 dark:text-amber-300"
                  : "text-muted-foreground"
            )}
          >
            {complete ? (
              <Check aria-hidden="true" className="h-3.5 w-3.5" />
            ) : needsAcceptance ? (
              <LockKeyhole aria-hidden="true" className="h-3.5 w-3.5" />
            ) : (
              <Clock3 aria-hidden="true" className="h-3.5 w-3.5" />
            )}
            {complete
              ? "Completed"
              : needsAcceptance
                ? "Needs audit acceptance"
                : "Finite assignment"}
          </span>
        </div>
        <h2
          id={`assignment-${assignment.id}`}
          className="mt-4 text-xl font-semibold leading-tight tracking-tight sm:text-2xl"
        >
          {assignment.title}
        </h2>
        <p className="mt-3 text-sm leading-6 text-muted-foreground">
          {assignment.brief}
        </p>
        <div className="mt-4 flex items-center gap-2 text-xs text-muted-foreground">
          <EntityIcon
            kind="agent"
            aria-hidden="true"
            className="h-3.5 w-3.5 shrink-0"
          />
          <span>
            Responsible agent ·{" "}
            <span className="font-medium text-foreground">
              {assignment.owner}
            </span>
          </span>
        </div>
        {assignment.outcome ? (
          <div className="mt-5 rounded-lg border border-border bg-background/70 p-3.5">
            <p className="text-[10px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
              Expected output
            </p>
            <p className="mt-1.5 text-xs leading-5 text-muted-foreground">
              {assignment.outcome}
            </p>
          </div>
        ) : null}
      </div>

      <div className="p-5 sm:p-6">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h3 className="text-xs font-semibold uppercase tracking-[0.12em] text-muted-foreground">
            Audit work
          </h3>
          <span className="font-mono text-xs tabular-nums text-muted-foreground">
            {completedCount} / {assignmentTasks.length} complete
          </span>
        </div>
        <ol className="mt-3 space-y-2">
          {assignmentTasks.map((task, index) => {
            const completed = task.status === "completed";
            const approval = task.status === "waiting_for_approval";
            const blocked = isTaskBlocked(task, tasks);
            const dependencies = task.dependsOn
              .map((id) => tasksById.get(id))
              .filter((dependency): dependency is ConceptTask =>
                Boolean(dependency)
              );
            const status = completed
              ? "Complete"
              : approval
                ? "Awaiting acceptance"
                : task.status === "running"
                  ? "In progress"
                  : blocked
                    ? "Scheduled · waiting"
                    : "Scheduled";

            return (
              <li key={task.id}>
                <button
                  type="button"
                  onClick={(event) => onOpenTask(task.id, event.currentTarget)}
                  aria-label={`${approval ? "Review" : "Open"} ${task.goal}`}
                  className={cn(
                    "group flex w-full min-w-0 items-start gap-3 rounded-lg border px-3 py-3 text-left transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background motion-reduce:transition-none sm:px-4",
                    approval
                      ? "border-amber-200 bg-amber-50/60 hover:bg-amber-50 dark:border-amber-800/60 dark:bg-amber-950/20 dark:hover:bg-amber-950/40"
                      : "border-transparent bg-muted/35 hover:border-border hover:bg-muted/65"
                  )}
                >
                  <span
                    aria-hidden="true"
                    className={cn(
                      "mt-0.5 flex h-6 w-6 shrink-0 items-center justify-center rounded-full border text-[10px] font-medium tabular-nums",
                      completed
                        ? "border-emerald-200 bg-emerald-50 text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-300"
                        : approval
                          ? "border-amber-300 text-amber-700 dark:border-amber-700 dark:text-amber-300"
                          : "border-border text-muted-foreground"
                    )}
                  >
                    {completed ? (
                      <Check className="h-3 w-3" />
                    ) : approval ? (
                      <LockKeyhole className="h-3 w-3" />
                    ) : (
                      String(index + 1).padStart(2, "0")
                    )}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="flex items-start gap-2">
                      <span className="min-w-0 flex-1 text-sm font-semibold leading-5">
                        {task.goal}
                      </span>
                      <ArrowUpRight
                        aria-hidden="true"
                        className="h-3.5 w-3.5 shrink-0 text-muted-foreground group-hover:text-foreground"
                      />
                    </span>
                    <span
                      className={cn(
                        "mt-1 block text-[11px] font-medium",
                        completed
                          ? "text-emerald-700 dark:text-emerald-300"
                          : approval
                            ? "text-amber-700 dark:text-amber-300"
                            : "text-muted-foreground"
                      )}
                    >
                      {status}
                    </span>
                    <span className="mt-1 block text-xs leading-5 text-muted-foreground">
                      {completed && task.outcome
                        ? task.outcome.label
                        : task.activity}
                    </span>
                    {dependencies.length > 0 ? (
                      <span className="mt-2 block border-t border-border/60 pt-2 text-[11px] leading-5 text-muted-foreground">
                        {dependencies.map((dependency) => (
                          <span key={dependency.id} className="block">
                            {dependency.status === "completed"
                              ? "Evidence ready: "
                              : "Depends on: "}
                            {dependency.goal}
                          </span>
                        ))}
                      </span>
                    ) : null}
                    {approval ? (
                      <span className="mt-2 block text-xs font-semibold text-amber-800 dark:text-amber-200">
                        Review audit acceptance →
                      </span>
                    ) : null}
                  </span>
                </button>
              </li>
            );
          })}
        </ol>
      </div>
    </section>
  );
}

export default function AssignmentsHypothesis({
  tasks,
  workstreams,
  onOpenTask,
}: ConceptViewProps) {
  const assignments = [...workstreams].sort((first, second) => {
    if (first.kind === second.kind) return 0;
    return first.kind === "ongoing" ? -1 : 1;
  });

  return (
    <div
      aria-label="Delegated assignments"
      className="grid min-w-0 items-start gap-5 xl:grid-cols-2"
    >
      {assignments.map((assignment) =>
        assignment.kind === "ongoing" ? (
          <OngoingAssignment
            key={assignment.id}
            assignment={assignment}
            tasks={tasks}
            onOpenTask={onOpenTask}
          />
        ) : (
          <OneOffAssignment
            key={assignment.id}
            assignment={assignment}
            tasks={tasks}
            onOpenTask={onOpenTask}
          />
        )
      )}
    </div>
  );
}
