"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname, useRouter } from "next/navigation";
import { Play, Power, PowerOff } from "lucide-react";
import { toast } from "sonner";
import { useFormSubmittingState } from "@/app/(main)/agents/shared/useFormSubmittingState";
import DeleteButton from "@/components/DeleteButton/DeleteButton";
import { Button } from "@/components/ui/button";
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
  const router = useRouter();
  const pathname = usePathname();
  const tCreate = useTranslations("TriggersPage.create");
  const t = useTranslations("TriggersPage.detail");
  // The form only exists on the overview route; the executions and metrics tabs
  // share this header and have nothing to submit.
  const isOverview = pathname === `/triggers/${triggerId}`;
  const isSaving = useFormSubmittingState("create-trigger-form");
  const [isToggling, setIsToggling] = useState(false);
  const [active, setActive] = useState(isActive);
  const [isRunning, setIsRunning] = useState(false);
  // Why a run produced no task. Shown next to the button rather than in a toast:
  // it is the answer to what was just asked, and it is worth re-reading.
  const [skipped, setSkipped] = useState<string | null>(null);
  const handleDelete = async (id: string) => {
    const result = await deleteTriggerAction(id);
    return result.error
      ? { error: { detail: [{ msg: result.error }] } }
      : { error: undefined };
  };

  const handleToggle = async () => {
    setIsToggling(true);
    try {
      const action = active ? disableTriggerAction : enableTriggerAction;
      const { error } = await action(triggerId);
      if (error) {
        toast.error(
          active ? "Failed to disable trigger" : "Failed to enable trigger"
        );
      } else {
        setActive(!active);
        toast.success(active ? "Trigger disabled" : "Trigger enabled");
        router.refresh();
      }
    } finally {
      setIsToggling(false);
    }
  };

  const handleRunNow = async () => {
    setIsRunning(true);
    setSkipped(null);
    try {
      const result = await runTriggerNowAction(triggerId);
      if (!result.success) {
        toast.error(result.error);
        return;
      }
      if (result.taskId) {
        // The point of the button is watching the run, so go to it.
        router.push(`/tasks/${result.taskId}`);
        return;
      }
      setSkipped(result.reason ?? t("runSkipped"));
    } finally {
      setIsRunning(false);
    }
  };

  return (
    <div className="flex flex-wrap items-center gap-2 py-1 sm:flex-nowrap">
      {skipped && (
        <span className="text-xs text-muted-foreground" role="status">
          {skipped}
        </span>
      )}
      <Button
        size="xs"
        variant="outline"
        type="button"
        onClick={handleRunNow}
        disabled={isRunning}
        isLoading={isRunning}
      >
        <Play />
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
            Disable
          </>
        ) : (
          <>
            <Power />
            Enable
          </>
        )}
      </Button>
      {isOverview && (
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
        onDelete={handleDelete}
        redirectPath="/triggers"
        title="Delete Trigger"
        description={`Are you sure you want to delete "${triggerName}"? This action cannot be undone.`}
        successMessage="Trigger deleted"
        errorMessages={{
          failedToDelete: "Failed to delete trigger",
          unexpectedError: "Failed to delete trigger",
        }}
      />
    </div>
  );
}
