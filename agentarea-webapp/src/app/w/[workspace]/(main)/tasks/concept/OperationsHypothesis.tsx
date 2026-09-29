"use client";

import {
  ArrowRight,
  Check,
  CheckCircle2,
  CircleDot,
  LockKeyhole,
  Repeat2,
  ShieldAlert,
} from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { EntityIcon } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";
import {
  DEMO_TIME_ZONE,
  formatConceptDay,
  formatConceptTime,
  isTaskBlocked,
  type ConceptTask,
  type ConceptViewProps,
} from "./concept-data";

export default function OperationsHypothesis({
  tasks,
  workstreams,
  onOpenTask,
}: ConceptViewProps) {
  const attention: ConceptTask[] = [];
  const running: ConceptTask[] = [];
  const upcoming: ConceptTask[] = [];
  const completed: ConceptTask[] = [];
  const tasksById = new Map(tasks.map((task) => [task.id, task]));
  const workstreamsById = new Map(
    workstreams.map((workstream) => [workstream.id, workstream])
  );

  for (const task of tasks) {
    if (task.status === "completed") {
      completed.push(task);
    } else if (task.needsAttention || task.status === "waiting_for_approval") {
      attention.push(task);
    } else if (task.status === "running") {
      running.push(task);
    }
    if (task.status === "scheduled") upcoming.push(task);
  }

  upcoming.sort((first, second) =>
    (first.scheduledAt ?? "9999").localeCompare(second.scheduledAt ?? "9999")
  );

  return (
    <div className="grid min-w-0 items-start gap-8 lg:grid-cols-[minmax(0,1.55fr)_minmax(0,1fr)] lg:gap-10">
      <div className="min-w-0 space-y-8">
        <section
          aria-labelledby="operations-attention-heading"
          className="min-w-0"
        >
          <div className="mb-3 flex items-center justify-between gap-3">
            <h2
              id="operations-attention-heading"
              className="text-sm font-semibold tracking-tight"
            >
              Your intervention
            </h2>
            <span className="font-mono text-xs tabular-nums text-muted-foreground">
              {attention.length} pending
            </span>
          </div>

          {attention.length > 0 ? (
            <div className="space-y-3">
              {attention.map((task) => {
                const dependentTasks = tasks.filter(
                  (candidate) =>
                    candidate.status !== "completed" &&
                    candidate.dependsOn.includes(task.id)
                );
                const workstream = workstreamsById.get(task.workstreamId);

                return (
                  <article
                    key={task.id}
                    className="min-w-0 overflow-hidden rounded-lg border border-amber-300/80 bg-amber-50/70 dark:border-amber-800 dark:bg-amber-950/20"
                  >
                    <div className="h-1 bg-amber-500 dark:bg-amber-600" />
                    <div className="space-y-5 p-5 sm:p-6">
                      <div className="flex items-center gap-2 text-xs font-semibold text-amber-900 dark:text-amber-200">
                        <ShieldAlert
                          className="h-4 w-4 shrink-0"
                          aria-hidden="true"
                        />
                        {task.status === "waiting_for_approval"
                          ? "Approval required"
                          : "Needs your attention"}
                      </div>
                      <div className="space-y-2">
                        <h3 className="break-words text-xl font-semibold leading-tight tracking-tight sm:text-2xl">
                          {task.goal}
                        </h3>
                        <p className="max-w-prose break-words text-sm leading-relaxed text-muted-foreground">
                          {task.decision?.description ?? task.detail}
                        </p>
                      </div>
                      <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">
                        <span className="inline-flex min-w-0 items-center gap-1.5">
                          <EntityIcon
                            kind="agent"
                            className="h-3.5 w-3.5 shrink-0"
                          />
                          <span className="break-words">{task.agent}</span>
                        </span>
                        <span className="inline-flex min-w-0 items-center gap-1.5">
                          <EntityIcon
                            kind="project"
                            className="h-3.5 w-3.5 shrink-0"
                          />
                          <span className="break-words">
                            {workstream?.title ?? task.project}
                          </span>
                        </span>
                      </div>
                      {dependentTasks.length > 0 ? (
                        <div className="border-t border-amber-200/80 pt-4 dark:border-amber-900">
                          <p className="mb-1 text-xs font-medium text-amber-900 dark:text-amber-200">
                            Waiting on this decision
                          </p>
                          {dependentTasks.map((dependent) => (
                            <p
                              key={dependent.id}
                              className="break-words text-sm leading-relaxed"
                            >
                              {dependent.goal}
                              {dependent.scheduledAt ? (
                                <span className="text-muted-foreground">
                                  {" · "}
                                  {formatConceptDay(
                                    dependent.scheduledAt
                                  )} at{" "}
                                  {formatConceptTime(dependent.scheduledAt)}{" "}
                                  {DEMO_TIME_ZONE}
                                </span>
                              ) : null}
                            </p>
                          ))}
                        </div>
                      ) : null}
                      <button
                        type="button"
                        onClick={(event) =>
                          onOpenTask(task.id, event.currentTarget)
                        }
                        aria-label={`Review ${task.goal}`}
                        className={cn(
                          buttonVariants(),
                          "min-h-11 max-w-full whitespace-normal bg-amber-900 text-amber-50 hover:bg-amber-950 dark:bg-amber-300 dark:text-amber-950 dark:hover:bg-amber-200"
                        )}
                      >
                        {task.status === "waiting_for_approval"
                          ? "Review decision"
                          : "Review task"}
                        <ArrowRight className="h-4 w-4" aria-hidden="true" />
                      </button>
                    </div>
                  </article>
                );
              })}
            </div>
          ) : (
            <div
              className="rounded-lg border border-border bg-muted/30 p-5 sm:p-6"
              role="status"
            >
              <CheckCircle2
                className="mb-4 h-6 w-6 text-emerald-700 dark:text-emerald-400"
                aria-hidden="true"
              />
              <h3 className="text-xl font-semibold tracking-tight">
                Nothing needs your decision.
              </h3>
              <p className="mt-2 text-sm leading-relaxed text-muted-foreground">
                No pending interventions. Scheduled work keeps its planned time;
                completed decisions are recorded below.
              </p>
            </div>
          )}
        </section>

        <section
          aria-labelledby="operations-running-heading"
          className="min-w-0"
        >
          <div className="mb-2 flex items-center justify-between gap-3">
            <h2
              id="operations-running-heading"
              className="text-sm font-semibold tracking-tight"
            >
              Working now
            </h2>
            <span className="font-mono text-xs text-muted-foreground">
              {running.length} active
            </span>
          </div>
          {running.length > 0 ? (
            <ul className="divide-y divide-border">
              {running.map((task) => (
                <li key={task.id} className="min-w-0">
                  <button
                    type="button"
                    onClick={(event) =>
                      onOpenTask(task.id, event.currentTarget)
                    }
                    className="group flex w-full min-w-0 items-start gap-3 rounded-md py-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                  >
                    <CircleDot
                      className="mt-0.5 h-4 w-4 shrink-0 text-primary"
                      aria-hidden="true"
                    />
                    <span className="min-w-0 flex-1 space-y-1.5">
                      <span className="block break-words text-sm font-medium">
                        {task.goal}
                      </span>
                      <span className="block break-words text-xs leading-relaxed text-muted-foreground">
                        {task.activity}
                      </span>
                      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        <EntityIcon
                          kind="agent"
                          className="h-3.5 w-3.5 shrink-0"
                        />
                        <span className="break-words">{task.agent}</span>
                        <span className="sr-only"> · Running</span>
                      </span>
                    </span>
                    <ArrowRight
                      className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform group-hover:translate-x-0.5 motion-reduce:transform-none motion-reduce:transition-none"
                      aria-hidden="true"
                    />
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="py-4 text-sm text-muted-foreground">
              No work is running right now.
            </p>
          )}
        </section>

        <section
          aria-labelledby="operations-results-heading"
          className="min-w-0 border-t border-border pt-5"
        >
          <h2
            id="operations-results-heading"
            className="mb-3 text-xs font-medium text-muted-foreground"
          >
            Completed results · {completed.length}
          </h2>
          {completed.length > 0 ? (
            <ul className="space-y-1">
              {completed.map((task) => (
                <li key={task.id}>
                  <button
                    type="button"
                    onClick={(event) =>
                      onOpenTask(task.id, event.currentTarget)
                    }
                    aria-label={`View result: ${task.goal}`}
                    className="flex w-full min-w-0 items-start gap-2 rounded-md py-2 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                  >
                    <Check
                      className="mt-0.5 h-3.5 w-3.5 shrink-0 text-emerald-700 dark:text-emerald-400"
                      aria-hidden="true"
                    />
                    <span className="min-w-0 space-y-1">
                      <span className="block break-words text-xs font-medium">
                        {task.outcome?.label ?? task.goal}
                      </span>
                      <span className="block break-words text-xs leading-relaxed text-muted-foreground">
                        {task.outcome?.detail ?? task.activity}
                      </span>
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="text-xs text-muted-foreground">
              Completed results will appear here.
            </p>
          )}
        </section>
      </div>

      <aside
        aria-labelledby="operations-upcoming-heading"
        className="min-w-0 border-t border-border pt-6 lg:border-l lg:border-t-0 lg:pl-7 lg:pt-0"
      >
        <div className="mb-1 flex items-center justify-between gap-3">
          <h2
            id="operations-upcoming-heading"
            className="text-sm font-semibold tracking-tight"
          >
            Coming up
          </h2>
          <span className="font-mono text-[11px] text-muted-foreground">
            {DEMO_TIME_ZONE}
          </span>
        </div>
        <p className="mb-4 text-xs leading-relaxed text-muted-foreground">
          Scheduled tasks and projected recurrences
        </p>
        {upcoming.length > 0 ? (
          <ol className="divide-y divide-border">
            {upcoming.map((task) => {
              const projected = task.scheduleKind === "recurring-occurrence";
              const blocked = isTaskBlocked(task, tasks);
              const unresolved = task.dependsOn.filter(
                (id) => tasksById.get(id)?.status !== "completed"
              );

              return (
                <li key={task.id} className="min-w-0">
                  <button
                    type="button"
                    onClick={(event) =>
                      onOpenTask(task.id, event.currentTarget)
                    }
                    className="group block w-full min-w-0 space-y-2 rounded-md py-4 text-left transition-colors hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring motion-reduce:transition-none"
                  >
                    <span className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                      {task.scheduledAt ? (
                        <>
                          <time
                            dateTime={task.scheduledAt}
                            className="font-mono text-sm font-medium tabular-nums"
                          >
                            {formatConceptTime(task.scheduledAt)}
                          </time>
                          <span className="text-xs text-muted-foreground">
                            {formatConceptDay(task.scheduledAt)}
                          </span>
                        </>
                      ) : (
                        <span className="text-xs text-muted-foreground">
                          Time not set
                        </span>
                      )}
                    </span>
                    <span className="flex items-start gap-2">
                      <span className="min-w-0 flex-1 break-words text-sm font-medium leading-snug">
                        {task.goal}
                      </span>
                      <ArrowRight
                        className="h-3.5 w-3.5 shrink-0 text-muted-foreground"
                        aria-hidden="true"
                      />
                    </span>
                    <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <EntityIcon
                        kind="agent"
                        className="h-3.5 w-3.5 shrink-0"
                      />
                      <span className="break-words">{task.agent}</span>
                    </span>
                    <span
                      className={cn(
                        "inline-flex max-w-full items-center gap-1.5 rounded border px-1.5 py-0.5 text-[11px] leading-relaxed text-muted-foreground",
                        projected
                          ? "border-dashed border-border"
                          : "border-transparent bg-muted"
                      )}
                    >
                      {projected ? (
                        <Repeat2
                          className="h-3 w-3 shrink-0"
                          aria-hidden="true"
                        />
                      ) : null}
                      {projected
                        ? "Projected recurrence · not created"
                        : "Scheduled task"}
                    </span>
                    {blocked ? (
                      <span className="flex items-start gap-1.5 text-xs leading-relaxed text-muted-foreground">
                        <LockKeyhole
                          className="mt-0.5 h-3 w-3 shrink-0"
                          aria-hidden="true"
                        />
                        <span className="min-w-0 break-words">
                          Waiting on{" "}
                          {unresolved
                            .map(
                              (id) =>
                                tasksById.get(id)?.goal ?? "a prerequisite"
                            )
                            .join("; ")}
                        </span>
                      </span>
                    ) : task.dependsOn.length > 0 ? (
                      <span className="flex items-start gap-1.5 text-xs leading-relaxed text-emerald-700 dark:text-emerald-400">
                        <Check
                          className="mt-0.5 h-3 w-3 shrink-0"
                          aria-hidden="true"
                        />
                        <span>
                          Prerequisites complete · scheduled time unchanged
                        </span>
                      </span>
                    ) : null}
                  </button>
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="py-4 text-sm text-muted-foreground">
            No upcoming work in this scenario.
          </p>
        )}
      </aside>
    </div>
  );
}
