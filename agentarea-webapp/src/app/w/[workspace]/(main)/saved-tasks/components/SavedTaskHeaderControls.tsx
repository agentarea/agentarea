"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Play } from "lucide-react";
import { useFormSubmittingState } from "@/app/w/[workspace]/(main)/agents/shared/useFormSubmittingState";
import DeleteButton from "@/components/DeleteButton/DeleteButton";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { formatApiError } from "@/lib/api-errors";
import { deleteSavedTaskAction, runSavedTaskAction } from "../actions";
import { SAVED_TASK_FORM_ID } from "./SavedTaskForm";

/** Header of the saved task form: run it now, save it, delete it -- or cancel a new one. */
export default function SavedTaskHeaderControls({
  definition,
}: {
  definition?: { id: string; name: string };
}) {
  const t = useTranslations("SavedTasksPage");
  const tCommon = useTranslations("Common");
  const router = useWorkspaceRouter();
  const isSaving = useFormSubmittingState(SAVED_TASK_FORM_ID);
  const [isRunning, setIsRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleRun = async () => {
    if (!definition) return;
    setIsRunning(true);
    setError(null);
    try {
      const result = await runSavedTaskAction(definition.id);
      if (!result.success) {
        setError(result.error);
        return;
      }
      // The point of the button is watching the run, so go to it.
      router.push(`/tasks/${result.taskId}`);
    } catch (err) {
      console.error("Failed to run saved task", err);
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
      {definition ? (
        <Button
          size="xs"
          variant="outline"
          type="button"
          onClick={handleRun}
          disabled={isRunning}
          isLoading={isRunning}
        >
          <Play strokeWidth={2} />
          {t("run")}
        </Button>
      ) : (
        <Button asChild size="xs" variant="outline">
          <Link href="/saved-tasks">{tCommon("cancel")}</Link>
        </Button>
      )}
      <Button
        size="xs"
        type="submit"
        form={SAVED_TASK_FORM_ID}
        isLoading={isSaving}
        disabled={isSaving}
      >
        {t("form.save")}
      </Button>
      {definition && (
        <DeleteButton
          size="xs"
          itemId={definition.id}
          itemName={definition.name}
          onDelete={deleteSavedTaskAction}
          redirectPath="/saved-tasks"
          title={t("delete")}
          errorMessages={{ failedToDelete: t("deleteFailed") }}
        />
      )}
    </div>
  );
}
