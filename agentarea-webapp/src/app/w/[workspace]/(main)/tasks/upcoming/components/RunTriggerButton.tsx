"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { runTriggerNowAction } from "@/app/w/[workspace]/(main)/triggers/[id]/actions";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { RunButton } from "../../components/RunButton";

/** Starts the trigger's run now, ahead of its schedule, and opens it. */
export function RunTriggerButton({ triggerId }: { triggerId: string }) {
  const t = useTranslations("TasksPage");
  const router = useWorkspaceRouter();
  const [pending, startTransition] = useTransition();
  const [error, setError] = useState<string | null>(null);

  return (
    <RunButton
      pending={pending}
      error={error}
      onRun={() =>
        startTransition(async () => {
          const result = await runTriggerNowAction(triggerId);
          if (!result.success) return setError(result.error);
          if (result.taskId) return router.push(`/tasks/${result.taskId}`);
          setError(result.reason ?? t("runFailed"));
        })
      }
    />
  );
}
