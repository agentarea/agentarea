"use client";

import type { MouseEventHandler } from "react";
import { Check, X } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import { TaskStatus } from "@/components/TaskStatus";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { cn } from "@/lib/utils";
import { InboxEmptyState } from "@/app/(main)/inbox/components/InboxEmptyState";
import {
  formatRelative,
  type InboxCounts,
  type InboxTask,
  isPending,
  type FilterValue,
} from "@/app/(main)/inbox/components/inboxShared";

interface InboxTaskListProps {
  visible: InboxTask[];
  filter: FilterValue;
  counts: InboxCounts;
  selectedId: string | null;
  checked: Set<string>;
  anyChecked: boolean;
  effectiveStatus: (task: InboxTask) => string;
  onSelect: (id: string) => void;
  onToggleCheck: (id: string) => void;
  onResolve: (task: InboxTask, approved: boolean) => void;
}

export function InboxTaskList({
  visible,
  filter,
  counts,
  selectedId,
  checked,
  anyChecked,
  effectiveStatus,
  onSelect,
  onToggleCheck,
  onResolve,
}: InboxTaskListProps) {
  if (visible.length === 0) {
    return <InboxEmptyState filter={filter} counts={counts} />;
  }

  return (
    <>
      {visible.map((task) => {
        const id = String(task.id);
        const status = effectiveStatus(task);
        const pending = isPending(status);
        const isSelected = id === selectedId;
        const isChecked = checked.has(id);
        const actionPreview = task.escalation_tool_name
          ? `Request ${task.escalation_tool_name}`
          : pending
            ? "Waiting for approval"
            : resultPreview(task);

        return (
          <InteractiveListRow
            key={id}
            onClick={() => onSelect(id)}
            selected={isSelected}
            className="mx-1 my-px items-start rounded-lg px-3 py-3 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset sm:px-4 [&>span[aria-hidden]]:hidden"
            dividerClassName=""
            selectedClassName="bg-muted/75 dark:bg-zinc-800/80"
            showIndicator={false}
            start={
              <span className="relative h-9 w-9 shrink-0">
                <AgentAvatar
                  agent={{
                    id: task.agent_id || task.agent_name || id,
                    name: task.agent_name || "Unknown agent",
                  }}
                  size="md"
                />
                {pending && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleCheck(id);
                    }}
                    onKeyDown={(e) => e.stopPropagation()}
                    className={cn(
                      "absolute -left-1 -top-1 z-10 grid h-4 w-4 place-items-center rounded-[4px] border bg-background/95 transition",
                      isChecked
                        ? "border-primary bg-primary text-white opacity-100"
                        : "border-muted-foreground/50 text-transparent",
                      !isChecked && !anyChecked &&
                        "opacity-0 group-hover:opacity-100",
                      "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                    )}
                    aria-label="Select task"
                    aria-checked={isChecked}
                    role="checkbox"
                  >
                    <Check size={11} strokeWidth={3} />
                  </button>
                )}
              </span>
            }
            end={
              <span className="flex shrink-0 flex-col items-end gap-1 text-right">
                <TaskStatus status={status} caption="never" />
                <span className="whitespace-nowrap text-[11px] text-muted-foreground">
                  {formatRelative(task.created_at)}
                </span>
              </span>
            }
            hoverActions={
              pending ? (
                <>
                  <ActionIcon
                    title="Approve"
                    tone="approve"
                    onClick={(e) => {
                      e.stopPropagation();
                      onResolve(task, true);
                    }}
                  />
                  <ActionIcon
                    title="Reject"
                    tone="reject"
                    onClick={(e) => {
                      e.stopPropagation();
                      onResolve(task, false);
                    }}
                  />
                </>
              ) : null
            }
          >
            <div className="min-w-0 flex-1 pt-px">
              <p className="truncate text-[13px] font-semibold leading-5">
                {task.description || "Untitled task"}
              </p>
              <div className="mt-0.5 flex min-w-0 items-center gap-2 text-[11.5px] text-muted-foreground">
                <span className="truncate font-medium text-foreground/75">
                  {task.agent_name || "Unknown agent"}
                </span>
                <span
                  aria-hidden
                  className="h-[3px] w-[3px] shrink-0 rounded-full bg-muted-foreground/50"
                />
                <span className="truncate">{actionPreview}</span>
              </div>
            </div>
          </InteractiveListRow>
        );
      })}
    </>
  );
}

function ActionIcon({
  title,
  tone,
  onClick,
}: {
  title: string;
  tone: "approve" | "reject";
  onClick: MouseEventHandler<HTMLButtonElement>;
}) {
  const Icon = tone === "approve" ? Check : X;

  return (
    <button
      onClick={onClick}
      title={title}
      aria-label={title}
      className={cn(
        "grid h-7 w-7 place-items-center rounded-md border border-border bg-background",
        tone === "approve"
          ? "text-emerald-600 hover:border-emerald-500 hover:bg-emerald-500/10"
          : "text-red-500 hover:border-red-500 hover:bg-red-500/10"
      )}
    >
      <Icon size={15} strokeWidth={2} />
    </button>
  );
}

function resultPreview(task: InboxTask): string {
  if (task.result) return "Result available";
  if (task.error || task.failure_reason) return "Task failed";
  return "Task activity";
}
