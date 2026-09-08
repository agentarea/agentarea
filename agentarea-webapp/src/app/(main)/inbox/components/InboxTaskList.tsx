"use client";

import type { MouseEventHandler } from "react";
import { Check, X } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { getInboxStatusPresentation } from "@/lib/status";
import { cn } from "@/lib/utils";
import { InboxEmptyState } from "@/app/(main)/inbox/components/InboxEmptyState";
import {
  fmtCost,
  formatRelative,
  type InboxCounts,
  type InboxTask,
  isPending,
  type FilterValue,
} from "@/app/(main)/inbox/components/inboxShared";

function InboxStatusMark({ status }: { status: string }) {
  const presentation = getInboxStatusPresentation(status);

  return (
    <StatusIndicator
      tone={presentation.tone}
      pulse={presentation.pulse}
      size="default"
      aria-label={presentation.label}
      title={presentation.label}
      className="mt-1 shrink-0"
    />
  );
}

function AgentChip({ id, name }: { id?: string | null; name: string }) {
  return (
    <span className="inline-flex min-w-0 items-center gap-1.5">
      <AgentAvatar agent={{ id: id || name, name }} size="xs" />
      <span className="truncate font-mono text-[11px] text-foreground/80">
        {name}
      </span>
    </span>
  );
}

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
        const presentation = getInboxStatusPresentation(status);
        const pending = isPending(status);
        const isSelected = id === selectedId;
        const isChecked = checked.has(id);

        return (
          <InteractiveListRow
            key={id}
            onClick={() => onSelect(id)}
            selected={isSelected}
            className="items-start"
            decorationTone={presentation.tone}
            decorationVisible={isSelected}
            start={
              <>
                {pending && (
                  <button
                    onClick={(e) => {
                      e.stopPropagation();
                      onToggleCheck(id);
                    }}
                    className={cn(
                      "mt-1 grid h-4 w-4 shrink-0 place-items-center rounded-[4px] border transition",
                      isChecked
                        ? "border-primary bg-primary text-white opacity-100"
                        : "border-muted-foreground/50 text-transparent",
                      !isChecked && !anyChecked && "opacity-0 group-hover:opacity-100"
                    )}
                    aria-label="Select task"
                  >
                    <Check size={11} strokeWidth={3} />
                  </button>
                )}
                <InboxStatusMark status={status} />
              </>
            }
            end={
              <span className="w-[62px] text-right font-mono text-[11.5px] text-muted-foreground">
                {fmtCost(task.total_cost)}
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
            <div className="min-w-0 flex-1 pt-0">
              <p className="truncate text-[13px] font-[500] mb-1.5">
                {task.description || "Untitled task"}
              </p>
              <div className="mt-0.5 flex items-center gap-2 text-[11.5px] text-muted-foreground">
                <AgentChip
                  id={task.agent_id}
                  name={task.agent_name || "Unknown agent"}
                />
                <span className="h-[3px] w-[3px] shrink-0 rounded-full bg-muted-foreground/50" />
                <span className="whitespace-nowrap">
                  {formatRelative(task.created_at)}
                </span>
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
