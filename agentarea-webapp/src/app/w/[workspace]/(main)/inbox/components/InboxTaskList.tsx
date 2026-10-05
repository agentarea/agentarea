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
import { Button } from "@/components/ui/button";
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
            contentClassName="gap-3"
            start={
              <AgentAvatar
                agent={{
                  id: task.agent_id || task.agent_name || id,
                  name: agentName,
                }}
              />
            }
            leadingAction={
              pending ? (
                <button
                  type="button"
                  onClick={() => onToggleCheck(id)}
                  className="grid h-4 w-4 place-items-center rounded-[4px] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1 max-[767px]:h-11 max-[767px]:w-11"
                  aria-label={t("row.select")}
                  aria-checked={isChecked}
                  role="checkbox"
                >
                  <span
                    className={cn(
                      "grid h-4 w-4 place-items-center rounded-[4px] border bg-background/95 transition motion-reduce:transition-none",
                      isChecked
                        ? "border-primary bg-primary text-white opacity-100"
                        : "border-muted-foreground/50 text-transparent",
                      !isChecked &&
                        !anyChecked &&
                        "opacity-0 group-hover:opacity-100 group-focus-within:opacity-100 max-[767px]:opacity-100 [@media(hover:none)]:opacity-100"
                    )}
                  >
                    <Check size={11} strokeWidth={3} />
                  </span>
                </button>
              ) : null
            }
            leadingActionVisible={isChecked || anyChecked}
            endClassName="flex-col items-end gap-1"
            end={
              <>
                <TaskStatus status={status} caption="never" />
                <span className="whitespace-nowrap text-[11.5px] text-muted-foreground">
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
                    onClick={() => onResolve(task, true)}
                  />
                  <ActionIcon
                    title={t("reject")}
                    tone="reject"
                    onClick={() => onResolve(task, false)}
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
                <span className="truncate text-[11px] font-light text-muted-foreground">
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
    <Button
      type="button"
      size="xs"
      variant={tone === "approve" ? "primaryOutline" : "destructiveOutline"}
      className="w-6 px-0 motion-reduce:transition-none max-[767px]:h-11 max-[767px]:w-11"
      onClick={onClick}
      title={title}
      aria-label={title}
    >
      <Icon />
    </Button>
  );
}

function resultPreviewKey(
  task: InboxTask
): "row.resultAvailable" | "row.taskFailed" | "row.taskActivity" {
  if (task.result) return "row.resultAvailable";
  if (task.error || task.failure_reason) return "row.taskFailed";
  return "row.taskActivity";
}
