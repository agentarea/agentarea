"use client";

import { useTranslations } from "next-intl";
import { Play } from "lucide-react";
import { Button } from "@/components/ui/button";

/** The row action that starts something now; same look as a trigger's "Run now". */
export function RunButton({
  pending,
  onRun,
  error,
}: {
  pending: boolean;
  onRun: () => void;
  /** Why the last attempt did not start, next to the button. */
  error: string | null;
}) {
  const t = useTranslations("TasksPage");
  return (
    <div className="flex items-center justify-end gap-2">
      {error && (
        <span
          className="max-w-48 truncate text-xs text-muted-foreground"
          title={error}
        >
          {error}
        </span>
      )}
      <Button
        size="sm"
        variant="outline"
        type="button"
        isLoading={pending}
        disabled={pending}
        onClick={(e) => {
          e.preventDefault();
          e.stopPropagation();
          onRun();
        }}
      >
        <Play />
        {t("runNow")}
      </Button>
    </div>
  );
}
