"use client";

import { CheckCircle2, Clock3 } from "lucide-react";
import { TaskStatus } from "@/components/TaskStatus";
import { Button } from "@/components/ui/button";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { EntityIcon } from "@/lib/entity-icons";
import {
  formatConceptDay,
  formatConceptTime,
  isTaskBlocked,
  type ConceptTask,
} from "./concept-data";

type ConceptTaskDetailsProps = {
  task: ConceptTask | null;
  tasks: readonly ConceptTask[];
  onApprove: () => void;
  onOpenChange: (open: boolean) => void;
  onCloseAutoFocus: (event: Event) => void;
};

export default function ConceptTaskDetails({
  task,
  tasks,
  onApprove,
  onOpenChange,
  onCloseAutoFocus,
}: ConceptTaskDetailsProps) {
  const dependencies = task
    ? tasks.filter((candidate) => task.dependsOn.includes(candidate.id))
    : [];
  const following = task
    ? tasks.filter((candidate) => candidate.dependsOn.includes(task.id))
    : [];

  return (
    <Sheet open={Boolean(task)} onOpenChange={onOpenChange}>
      <SheetContent
        className="w-full overflow-y-auto overscroll-contain p-0 sm:max-w-lg"
        onCloseAutoFocus={onCloseAutoFocus}
      >
        {task && (
          <>
            <SheetHeader className="border-b border-border px-6 pb-5 pt-8 text-left">
              <TaskStatus status={task.status} caption="auto" />
              <SheetTitle className="pr-3 text-lg leading-7">
                {task.goal}
              </SheetTitle>
              <SheetDescription>
                Demo scenario only. No real task or external action is changed.
              </SheetDescription>
            </SheetHeader>
            <div className="space-y-6 px-6 py-5">
              <div className="space-y-2">
                <p className="text-sm font-medium">{task.activity}</p>
                <p className="text-sm leading-6 text-muted-foreground">
                  {task.detail}
                </p>
              </div>
              <dl className="grid gap-4 text-sm sm:grid-cols-2">
                <div className="min-w-0">
                  <dt className="text-xs text-muted-foreground">
                    Responsible agent
                  </dt>
                  <dd className="mt-1 flex items-center gap-2">
                    <EntityIcon kind="agent" className="h-4 w-4 shrink-0" />
                    {task.agent}
                  </dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-xs text-muted-foreground">Project</dt>
                  <dd className="mt-1 flex items-center gap-2">
                    <EntityIcon kind="project" className="h-4 w-4 shrink-0" />
                    {task.project}
                  </dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-xs text-muted-foreground">Started by</dt>
                  <dd className="mt-1">{task.source}</dd>
                </div>
                <div className="min-w-0">
                  <dt className="text-xs text-muted-foreground">
                    Scheduled start
                  </dt>
                  <dd className="mt-1 tabular-nums">
                    {task.scheduledAt
                      ? `${formatConceptDay(task.scheduledAt)} · ${formatConceptTime(task.scheduledAt)} UTC`
                      : "No scheduled start"}
                  </dd>
                </div>
              </dl>

              {task.scheduleKind === "recurring-occurrence" && (
                <p className="rounded-lg border border-border bg-muted/40 p-3 text-sm text-muted-foreground">
                  Recurring occurrence preview · a task has not been created
                  yet.
                </p>
              )}

              {dependencies.length > 0 && (
                <section aria-label="Prerequisites" className="space-y-2">
                  <h3 className="text-sm font-semibold">
                    Before this can proceed
                  </h3>
                  <ul className="space-y-2">
                    {dependencies.map((dependency) => {
                      const ready = dependency.status === "completed";
                      const Icon = ready ? CheckCircle2 : Clock3;
                      return (
                        <li
                          key={dependency.id}
                          className="flex items-start gap-2 text-sm"
                        >
                          <Icon
                            aria-hidden="true"
                            className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground"
                          />
                          <span>
                            {dependency.goal}
                            <span className="block text-xs text-muted-foreground">
                              {ready
                                ? "Complete"
                                : "Still waiting for this step"}
                            </span>
                          </span>
                        </li>
                      );
                    })}
                  </ul>
                </section>
              )}

              {task.decision && task.status === "waiting_for_approval" && (
                <section className="space-y-3 rounded-xl border border-amber-200 bg-amber-50/70 p-4 dark:border-amber-900 dark:bg-amber-950/25">
                  <h3 className="text-sm font-semibold text-amber-950 dark:text-amber-100">
                    Your decision
                  </h3>
                  <p className="text-sm leading-6 text-amber-900 dark:text-amber-200">
                    {task.decision.description}
                  </p>
                  <Button
                    type="button"
                    onClick={onApprove}
                    disabled={isTaskBlocked(task, tasks)}
                    className="w-full"
                  >
                    {task.decision.label}
                  </Button>
                  <p className="text-xs text-amber-800 dark:text-amber-300">
                    Updates this demo in all three perspectives. Nothing is
                    sent.
                  </p>
                </section>
              )}

              {task.outcome && (
                <section className="space-y-2 rounded-xl border border-border bg-muted/40 p-4">
                  <h3 className="flex items-center gap-2 text-sm font-semibold">
                    <CheckCircle2
                      aria-hidden="true"
                      className="h-4 w-4 shrink-0"
                    />
                    {task.outcome.label}
                  </h3>
                  <p className="text-sm leading-6 text-muted-foreground">
                    {task.outcome.detail}
                  </p>
                </section>
              )}

              {following.length > 0 && (
                <section aria-label="Following work" className="space-y-3">
                  <h3 className="text-sm font-semibold">What follows</h3>
                  {following.map((next) => (
                    <div
                      key={next.id}
                      className="border-l-2 border-border pl-3 text-sm"
                    >
                      <p className="font-medium">{next.goal}</p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {next.scheduledAt
                          ? `${formatConceptDay(next.scheduledAt)} · ${formatConceptTime(next.scheduledAt)} UTC`
                          : "After its prerequisites are complete"}
                      </p>
                      <p className="mt-1 text-xs text-muted-foreground">
                        {isTaskBlocked(next, tasks)
                          ? "Waiting for prerequisites"
                          : next.scheduledAt
                            ? "Prerequisites complete · waiting for scheduled time"
                            : "Prerequisites complete"}
                      </p>
                    </div>
                  ))}
                </section>
              )}
            </div>
          </>
        )}
      </SheetContent>
    </Sheet>
  );
}
