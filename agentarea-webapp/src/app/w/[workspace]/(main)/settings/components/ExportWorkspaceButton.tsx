"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { Download, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { useWorkspaceSlug } from "@/hooks/useWorkspaceNavigation";
import { exportWorkspaceAction } from "../actions";

export default function ExportWorkspaceButton() {
  const t = useTranslations("SettingsPage.workspace");
  const slug = useWorkspaceSlug();
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const exportWorkspace = () => {
    setError(null);
    startTransition(async () => {
      const result = await exportWorkspaceAction();
      if (result.error !== undefined) {
        setError(result.error);
        return;
      }
      const url = URL.createObjectURL(
        new Blob([result.data], { type: "application/x-yaml" })
      );
      const link = document.createElement("a");
      link.href = url;
      link.download = `${slug ?? "workspace"}.yaml`;
      link.click();
      URL.revokeObjectURL(url);
    });
  };

  return (
    <div className="flex flex-col items-start gap-2 md:items-end">
      <Button
        onClick={exportWorkspace}
        variant="outline"
        size="sm"
        className="gap-1"
        disabled={pending}
      >
        {pending ? <Loader2 className="animate-spin" /> : <Download />}
        {t("export")}
      </Button>
      {error && (
        <p role="alert" className="max-w-sm text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
