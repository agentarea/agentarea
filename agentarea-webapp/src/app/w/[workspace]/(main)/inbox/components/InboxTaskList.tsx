"use client";

import type { MouseEventHandler } from "react";
import { useFormatter, useNow, useTranslations } from "next-intl";
import { Check, X } from "lucide-react";
import { InboxEmptyState } from "@/app/w/[workspace]/(main)/inbox/components/InboxEmptyState";
import {
  formatRelative,
  isPending,
  type FilterValue,
  type InboxCounts,
  type InboxTask,
} from "@/app/w/[workspace]/(main)/inbox/components/inboxShared";
import { AgentAvatar } from "@/components/AgentAvatar";
import { TaskStatus } from "@/components/TaskStatus";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { cn } from "@/lib/utils";

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
  const t = useTranslations("InboxPage");
  const format = useFormatter();
  const now = useNow({ updateInterval: 60_000 });

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
        const agentName = task.agent_name || t("row.unknownAgent");
        const actionPreview = task.escalation_tool_name
          ? t("row.request", { tool: task.escalation_tool_name })
          : pending
            ? t("row.waiting")
            : t(resultPreviewKey(task));

        // Same row as the Skills list: the shared InteractiveListRow with its
        // own dividers, hover hatch and indicator, not a restyled card.
        return (
          <InteractiveListRow
            key={id}
            onClick={() => onSelect(id)}
            selected={isSelected}
            className="focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset"
            contentClassName="gap-3"
            start={
              <span className="relative">
                <AgentAvatar
                  agent={{
                    id: task.agent_id || task.agent_name || id,
                    name: agentName,
                  }}
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
                      !isChecked &&
                        !anyChecked &&
                        "opacity-0 group-hover:opacity-100",
                      "focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1"
                    )}
                    aria-label={t("row.select")}
                    aria-checked={isChecked}
                    role="checkbox"
                  >
                    <Check size={11} strokeWidth={3} />
                  </button>
                )}
              </span>
            }
            endClassName="flex-col items-end gap-1"
            end={
              <>
                <TaskStatus status={status} caption="never" />
                <span className="whitespace-nowrap text-[11.5px] text-muted-foreground/80">
                  {formatRelative(format, now, task.created_at)}
                </span>
              </>
            }
            hoverActionsClassName="bg-gradient-to-l from-muted/60 via-muted/60 to-transparent dark:from-zinc-800/50 dark:via-zinc-800/50"
            hoverActions={
              pending ? (
                <>
                  <ActionIcon
                    title={t("approve")}
                    tone="approve"
                    onClick={(e) => {
                      e.stopPropagation();
                      onResolve(task, true);
                    }}
                  />
                  <ActionIcon
                    title={t("reject")}
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
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium text-foreground">
                {task.description || t("row.untitled")}
              </p>
              <div className="mt-0.5 flex min-w-0 items-center gap-2 text-[12px] text-muted-foreground">
                <span className="truncate text-foreground/75">{agentName}</span>
                <span
                  aria-hidden
                  className="h-[3px] w-[3px] shrink-0 rounded-full bg-muted-foreground/50"
                />
                <span className="truncate text-[11px] font-light text-muted-foreground/70">
                  {actionPreview}
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

function resultPreviewKey(
  task: InboxTask
): "row.resultAvailable" | "row.taskFailed" | "row.taskActivity" {
  if (task.result) return "row.resultAvailable";
  if (task.error || task.failure_reason) return "row.taskFailed";
  return "row.taskActivity";
}
