"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Pause, Play, Square } from "lucide-react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useTaskActions } from "@/hooks/useTaskActions";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import {
  pauseAgentTaskAction,
  resumeAgentTaskAction,
} from "@/lib/server-actions";
import { useTaskContext } from "../TaskContext";

const FINISHED_STATUSES = ["completed", "failed", "cancelled"];

type Control = "pause" | "resume" | "cancel";

/**
 * Pause, resume and cancel for the open task. A pause is a signal the workflow
 * honours at its next step and does not change the task's status: the status
 * endpoint reports it as `paused`, and this control's own last action wins
 * until the page reloads that status.
 */
export function TaskControls() {
  const t = useTranslations("TasksPage.controls");
  const { task, taskStatus, liveStatus, refresh } = useTaskContext();
  const actions = useTaskActions(task?.agent_id ?? null, task?.id ?? null);
  const [paused, setPaused] = useState<boolean | null>(null);
  const [busy, setBusy] = useState<Control | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [confirmCancel, setConfirmCancel] = useState(false);

  if (!task) return null;
  const status = liveStatus ?? taskStatus?.status ?? task.status;
  if (FINISHED_STATUSES.includes(status)) return null;

  async function run(control: Control) {
    if (!task) return;
    setBusy(control);
    setError(null);
    const failed = t(`${control}Failed`);
    try {
      const result =
        control === "pause"
          ? await pauseAgentTaskAction(task.agent_id, task.id)
          : control === "resume"
            ? await resumeAgentTaskAction(task.agent_id, task.id)
            : await actions.cancel();
      if (result.error) {
        setError(apiErrorMessage(result, failed));
        return;
      }
      if (control === "pause") setPaused(true);
      if (control === "resume") setPaused(false);
      if (control === "cancel") {
        setConfirmCancel(false);
        await refresh();
      }
    } catch (e) {
      console.error(`Failed to ${control} task`, e);
      setError(`${failed}: ${formatApiError(e)}`);
    } finally {
      setBusy(null);
    }
  }

  const isPaused =
    paused ?? (taskStatus?.paused === true || status === "paused");

  return (
    <div className="flex min-w-0 items-center gap-1.5">
      {error && (
        <StatusIndicator
          kind="failed"
          size="sm"
          className="min-w-0 max-w-[16rem] truncate text-xs"
          title={error}
        >
          {error}
        </StatusIndicator>
      )}
      {isPaused ? (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() => run("resume")}
          disabled={busy !== null}
          aria-label={t("resume")}
        >
          {busy === "resume" ? <LoadingSpinner size="sm" /> : <Play />}
          <span className="hidden sm:inline">{t("resume")}</span>
        </Button>
      ) : (
        status === "running" && (
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => run("pause")}
            disabled={busy !== null}
            aria-label={t("pause")}
          >
            {busy === "pause" ? <LoadingSpinner size="sm" /> : <Pause />}
            <span className="hidden sm:inline">{t("pause")}</span>
          </Button>
        )
      )}
      <Button
        type="button"
        variant="outline"
        size="sm"
        onClick={() => setConfirmCancel(true)}
        disabled={busy !== null}
        aria-label={t("cancel")}
        className="text-red-600 hover:border-red-500 hover:bg-red-500/10 hover:text-red-600"
      >
        <Square />
        <span className="hidden sm:inline">{t("cancel")}</span>
      </Button>

      <Dialog
        open={confirmCancel}
        onOpenChange={(open) =>
          !open && busy !== "cancel" && setConfirmCancel(false)
        }
      >
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>{t("cancelTitle")}</DialogTitle>
            <DialogDescription>{t("cancelDescription")}</DialogDescription>
          </DialogHeader>
          {error && (
            <StatusIndicator kind="failed" size="sm" className="text-xs">
              {error}
            </StatusIndicator>
          )}
          <DialogFooter className="gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={() => setConfirmCancel(false)}
              disabled={busy === "cancel"}
            >
              {t("keepRunning")}
            </Button>
            <Button
              type="button"
              variant="destructive"
              size="sm"
              onClick={() => run("cancel")}
              disabled={busy === "cancel"}
            >
              {busy === "cancel" ? (
                <LoadingSpinner variant="light" size="sm" />
              ) : (
                <Square />
              )}
              {t("cancelConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
