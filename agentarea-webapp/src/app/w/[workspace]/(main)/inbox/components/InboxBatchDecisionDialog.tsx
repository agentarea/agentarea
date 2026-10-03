"use client";

import { useEffect, useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Check, X } from "lucide-react";
import type { InboxTask } from "@/app/w/[workspace]/(main)/inbox/components/inboxShared";
import { AgentAvatar } from "@/components/AgentAvatar";
import {
  approveButtonClassName,
  rejectButtonClassName,
} from "@/components/Approvals/ApprovalDecisionCard";
import { EscalationArguments } from "@/components/Approvals/EscalationArguments";
import { usePendingEscalation } from "@/components/Approvals/usePendingEscalation";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Textarea } from "@/components/ui/textarea";

interface InboxBatchDecisionDialogProps {
  /** The decision to confirm; null keeps the dialog closed. */
  approved: boolean | null;
  tasks: InboxTask[];
  onConfirm: (approved: boolean, comment: string) => void;
  onCancel: () => void;
}

/**
 * Confirmation before deciding several approvals at once: every call that is
 * about to run (or be refused) is listed with its exact arguments, and one
 * comment travels with all the decisions.
 */
export function InboxBatchDecisionDialog({
  approved,
  tasks,
  onConfirm,
  onCancel,
}: InboxBatchDecisionDialogProps) {
  const t = useTranslations("InboxPage.batch");
  const commentId = useId();
  const [comment, setComment] = useState("");
  const open = approved !== null;

  useEffect(() => {
    if (open) setComment("");
  }, [open]);

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onCancel()}>
      <DialogContent className="flex max-h-[85vh] max-w-2xl flex-col">
        <DialogHeader>
          <DialogTitle>
            {approved
              ? t("approveTitle", { count: tasks.length })
              : t("rejectTitle", { count: tasks.length })}
          </DialogTitle>
          <DialogDescription>
            {approved ? t("approveDescription") : t("rejectDescription")}
          </DialogDescription>
        </DialogHeader>
        <ul className="-mx-1 min-h-0 flex-1 space-y-2 overflow-y-auto px-1">
          {tasks.map((task) => (
            <BatchDecisionRow key={String(task.id)} task={task} />
          ))}
        </ul>
        <div className="space-y-1.5">
          <label
            htmlFor={commentId}
            className="text-xs font-medium text-muted-foreground"
          >
            {t("commentLabel")}
          </label>
          <Textarea
            id={commentId}
            value={comment}
            onChange={(event) => setComment(event.target.value)}
            placeholder={t("commentPlaceholder")}
            className="min-h-[56px] text-sm"
          />
        </div>
        <DialogFooter className="gap-2">
          <Button type="button" variant="outline" size="sm" onClick={onCancel}>
            {t("cancel")}
          </Button>
          {approved ? (
            <button
              type="button"
              onClick={() => onConfirm(true, comment.trim())}
              className={approveButtonClassName}
            >
              <Check size={16} strokeWidth={2.2} aria-hidden />
              {t("approveConfirm", { count: tasks.length })}
            </button>
          ) : (
            <button
              type="button"
              onClick={() => onConfirm(false, comment.trim())}
              className={rejectButtonClassName}
            >
              <X size={16} strokeWidth={2} aria-hidden />
              {t("rejectConfirm", { count: tasks.length })}
            </button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function BatchDecisionRow({ task }: { task: InboxTask }) {
  const t = useTranslations("InboxPage");
  const agentName = task.agent_name || t("row.unknownAgent");
  const pending = usePendingEscalation(
    task.agent_id,
    String(task.id),
    task.escalation_id ?? ""
  );

  return (
    <li className="space-y-2 rounded-lg border border-border bg-muted/20 p-3">
      <div className="flex min-w-0 items-center gap-2">
        <AgentAvatar
          agent={{ id: task.agent_id || agentName, name: agentName }}
          size="xs"
        />
        <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-foreground">
          {task.description || t("row.untitled")}
        </span>
        {task.escalation_tool_name && (
          <code className="shrink-0 rounded bg-muted px-1.5 py-0.5 font-mono text-[11.5px] text-foreground/80">
            {task.escalation_tool_name}
          </code>
        )}
      </div>
      <EscalationArguments pending={pending} />
    </li>
  );
}
