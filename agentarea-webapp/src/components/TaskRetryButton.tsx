"use client";

import { useTranslations } from "next-intl";
import { RotateCcw } from "lucide-react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";

/**
 * Re-run the turn a failed task ended on. One control for every surface that
 * shows a failed task: the task page header and the agent chat.
 */
export function TaskRetryButton({
  busy,
  disabled = false,
  onRetry,
}: {
  busy: boolean;
  disabled?: boolean;
  onRetry: () => void;
}) {
  const t = useTranslations("TasksPage.controls");
  return (
    <Button
      type="button"
      variant="outline"
      size="sm"
      onClick={onRetry}
      disabled={busy || disabled}
      aria-label={t("retry")}
    >
      {busy ? <LoadingSpinner size="sm" /> : <RotateCcw />}
      <span className="hidden sm:inline">{t("retry")}</span>
    </Button>
  );
}
