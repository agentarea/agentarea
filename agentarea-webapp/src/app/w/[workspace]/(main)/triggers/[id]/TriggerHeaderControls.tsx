"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { useWorkspacePathname, useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { Play, Power, PowerOff } from "lucide-react";
import { useFormSubmittingState } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import DeleteButton from "@/components/DeleteButton/DeleteButton";
import { Button } from "@/components/ui/button";
import { formatApiError } from "@/lib/api-errors";
import {
  deleteTriggerAction,
  disableTriggerAction,
  enableTriggerAction,
  runTriggerNowAction,
} from "./actions";

export default function TriggerHeaderControls({
  triggerId,
  triggerName,
  isActive,
}: {
  triggerId: string;
  triggerName: string;
  isActive: boolean;
}) {
  const router = useWorkspaceRouter();
  const pathname = useWorkspacePathname();
  const tCreate = useTranslations("TriggersPage.create");
  const t = useTranslations("TriggersPage.detail");
  const tError = useTranslations("TriggersPage.error");
  // The form only lives on the edit route; the overview, executions and
  // metrics tabs share this header and have nothing to submit.
  const isEditing = pathname === `/triggers/${triggerId}/edit`;
  const isSaving = useFormSubmittingState("create-trigger-form");
  const [isToggling, setIsToggling] = useState(false);
  const [active, setActive] = useState(isActive);
  const [isRunning, setIsRunning] = useState(false);
  // Why a run produced no task. Shown next to the button:
  // it is the answer to what was just asked, and it is worth re-reading.
  const [skipped, setSkipped] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleToggle = async () => {
    setIsToggling(true);
    setError(null);
    try {
      const action = active ? disableTriggerAction : enableTriggerAction;
      const result = await action(triggerId);
      if (result.error) {
        setError(result.error);
      } else {
        setActive(!active);
        router.refresh();
      }
    } catch (err) {
      console.error("Failed to toggle trigger", err);
      setError(
        `${active ? tError("disableFailed") : tError("enableFailed")}: ${formatApiError(err)}`
      );
    } finally {
      setIsToggling(false);
    }
  };

  const handleRunNow = async () => {
    setIsRunning(true);
    setSkipped(null);
    setError(null);
    try {
      const result = await runTriggerNowAction(triggerId);
      if (!result.success) {
        setError(result.error);
        return;
      }
      if (result.taskId) {
        // The point of the button is watching the run, so go to it.
        router.push(`/tasks/${result.taskId}`);
        return;
      }
      setSkipped(result.reason ?? t("runSkipped"));
    } catch (err) {
      console.error("Failed to run trigger", err);
      setError(formatApiError(err));
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 py-1 sm:flex-nowrap">
      {error && (
        <span className="form-error max-w-md break-words" role="alert">
          {error}
        </span>
      )}
      {skipped && (
        <span className="text-xs text-muted-foreground" role="status">
          {skipped}
        </span>
      )}
      {/* Primary action of the page, in the same slot and shape as the agent
          header's "New task" — except on the edit form, where saving is. */}
      <Button
        size={isEditing ? "xs" : "sm"}
        variant={isEditing ? "outline" : "default"}
        className={
          isEditing ? undefined : "h-7 gap-1.5 px-3 text-[12.5px] font-semibold"
        }
        type="button"
        onClick={handleRunNow}
        disabled={isRunning}
        isLoading={isRunning}
      >
        <Play strokeWidth={2} />
        {t("runNow")}
      </Button>
      <Button
        size="xs"
        variant="outline"
        type="button"
        onClick={handleToggle}
        disabled={isToggling}
        isLoading={isToggling}
      >
        {active ? (
          <>
            <PowerOff />
            {t("disable")}
          </>
        ) : (
          <>
            <Power />
            {t("enable")}
          </>
        )}
      </Button>
      {isEditing && (
        <Button
          size="xs"
          type="submit"
          form="create-trigger-form"
          isLoading={isSaving}
          disabled={isSaving}
        >
          {tCreate("updateButton")}
        </Button>
      )}
      <DeleteButton
        size="xs"
        itemId={triggerId}
        itemName={triggerName}
        onDelete={deleteTriggerAction}
        redirectPath="/triggers"
        title={t("delete")}
        errorMessages={{ failedToDelete: tError("deleteFailed") }}
      />
    </div>
  );
}
