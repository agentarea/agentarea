"use client";

import { useRef, useState } from "react";
import Link from "@/components/WorkspaceLink";
import { useSearchParams } from "next/navigation";
import { CheckCircle2, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import AssignmentsHypothesis from "./AssignmentsHypothesis";
import {
  CONCEPT_TASKS,
  CONCEPT_WORKSTREAMS,
  isTaskBlocked,
  type ConceptTask,
} from "./concept-data";
import ConceptTaskDetails from "./ConceptTaskDetails";
import OperationsHypothesis from "./OperationsHypothesis";
import TimelineHypothesis from "./TimelineHypothesis";

const HYPOTHESES = [
  {
    id: "operations",
    letter: "A",
    label: "Operations",
    question: "Where do I need to step in, and what happens next?",
    component: OperationsHypothesis,
  },
  {
    id: "timeline",
    letter: "B",
    label: "Timeline",
    question: "What is happening now, and how is the next week arranged?",
    component: TimelineHypothesis,
  },
  {
    id: "assignments",
    letter: "C",
    label: "Assignments",
    question: "What have I delegated, and how is each assignment progressing?",
    component: AssignmentsHypothesis,
  },
] as const;

export default function TasksConcept() {
  const searchParams = useSearchParams();
  const hypothesis =
    HYPOTHESES.find((item) => item.id === searchParams.get("variant")) ??
    HYPOTHESES[0];
  const View = hypothesis.component;
  const [tasks, setTasks] = useState<readonly ConceptTask[]>(CONCEPT_TASKS);
  const [selectedTaskId, setSelectedTaskId] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const openerRef = useRef<HTMLElement | null>(null);
  const fallbackRef = useRef<HTMLAnchorElement | null>(null);
  const selectedTask = tasks.find((task) => task.id === selectedTaskId) ?? null;
  const demoChanged = tasks !== CONCEPT_TASKS;

  function openTask(id: string, opener: HTMLElement) {
    openerRef.current = opener;
    setSelectedTaskId(id);
  }

  function approveDemo() {
    if (
      !selectedTask?.decision ||
      selectedTask.status !== "waiting_for_approval" ||
      isTaskBlocked(selectedTask, tasks)
    ) {
      return;
    }

    setTasks((current) =>
      current.map((task) =>
        task.id === selectedTask.id
          ? {
              ...task,
              status: "completed",
              needsAttention: false,
              activity:
                "Demo audit accepted. Scheduled follow-up keeps its planned start time.",
              outcome: {
                label: "Migration audit accepted",
                detail:
                  "The reviewed migration SEO audit and prioritized checklist are accepted. No site changes were published by this demo.",
              },
            }
          : task
      )
    );
    setSelectedTaskId(null);
    setAnnouncement(
      "Demo audit accepted. The finite migration audit is complete; ongoing SEO remains active and scheduled work keeps its planned time."
    );
  }

  return (
    <div className="flex min-h-full min-w-0 flex-col gap-6 p-4 lg:p-6">
      <header className="space-y-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">Tasks</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Three perspectives. The same agent work.
            </p>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="sm"
            disabled={!demoChanged}
            onClick={() => {
              setTasks(CONCEPT_TASKS);
              setSelectedTaskId(null);
              setAnnouncement(
                "Demo reset. The migration SEO audit needs acceptance again."
              );
            }}
          >
            <RotateCcw aria-hidden="true" />
            Reset demo
          </Button>
        </div>
        <nav
          aria-label="Concept hypotheses"
          className="grid grid-cols-3 gap-1 rounded-xl border border-border bg-muted/40 p-1"
        >
          {HYPOTHESES.map((item) => {
            const selected = hypothesis.id === item.id;
            return (
              <Link
                key={item.id}
                ref={selected ? fallbackRef : undefined}
                href={`/tasks/concept?variant=${item.id}`}
                replace
                scroll={false}
                aria-current={selected ? "page" : undefined}
                className={cn(
                  "flex min-h-11 min-w-0 items-center justify-center gap-2 rounded-lg px-2 py-2 text-xs font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring sm:text-sm",
                  selected
                    ? "bg-background text-foreground shadow-sm ring-1 ring-border"
                    : "text-muted-foreground hover:bg-background/60 hover:text-foreground"
                )}
              >
                <span
                  aria-hidden="true"
                  className={cn(
                    "hidden h-5 w-5 shrink-0 items-center justify-center rounded text-[10px] sm:flex",
                    selected ? "bg-foreground text-background" : "bg-muted"
                  )}
                >
                  {item.letter}
                </span>
                {item.label}
              </Link>
            );
          })}
        </nav>
        <p className="text-sm text-muted-foreground">{hypothesis.question}</p>
      </header>

      <div
        role="status"
        aria-live="polite"
        aria-atomic="true"
        className={announcement ? undefined : "sr-only"}
      >
        {announcement && (
          <p className="flex items-start gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2 text-sm">
            <CheckCircle2
              aria-hidden="true"
              className="mt-0.5 h-4 w-4 shrink-0"
            />
            {announcement}
          </p>
        )}
      </div>

      <View
        tasks={tasks}
        workstreams={CONCEPT_WORKSTREAMS}
        onOpenTask={openTask}
      />

      <ConceptTaskDetails
        task={selectedTask}
        tasks={tasks}
        onApprove={approveDemo}
        onOpenChange={(open) => {
          if (!open) setSelectedTaskId(null);
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          const opener = openerRef.current;
          if (opener?.isConnected) opener.focus();
          else fallbackRef.current?.focus();
          openerRef.current = null;
        }}
      />
    </div>
  );
}
