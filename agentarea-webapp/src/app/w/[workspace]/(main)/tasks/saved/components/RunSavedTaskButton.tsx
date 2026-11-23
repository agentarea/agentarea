"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { RunButton } from "../../components/RunButton";
import { runSavedTask } from "../actions";

export function RunSavedTaskButton({ definitionId }: { definitionId: string }) {
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
          const taskId = await runSavedTask(definitionId);
          setError(taskId ? null : t("runFailed"));
          if (taskId) router.push(`/tasks/${taskId}`);
        })
      }
    />
  );
}
