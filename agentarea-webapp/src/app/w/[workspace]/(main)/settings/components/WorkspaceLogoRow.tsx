"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WorkspaceIcon } from "@/components/WorkspaceIcon";
import { useFileDrop } from "@/hooks/use-file-drop";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { cn } from "@/lib/utils";
import type { Workspace } from "@/lib/workspaces";
import {
  deleteWorkspaceLogoAction,
  uploadWorkspaceLogoAction,
} from "../actions";
import SettingsRow from "./SettingsRow";

// The API's limits; checked here so a file it would refuse never leaves the browser.
const LOGO_MAX_BYTES = 1024 * 1024;
const LOGO_TYPES = ["image/png", "image/jpeg", "image/webp"];

/** The workspace logo: what it is now, a drop zone for a new one, and removal. */
export default function WorkspaceLogoRow({
  workspace,
}: {
  workspace: Workspace;
}) {
  const t = useTranslations("SettingsPage.workspace");
  const router = useWorkspaceRouter();
  const [error, setError] = useState<string | null>(null);
  const [pending, startTransition] = useTransition();

  const run = (action: () => Promise<{ error?: string }>) => {
    setError(null);
    startTransition(async () => {
      const result = await action();
      if (result.error !== undefined) {
        setError(result.error);
        return;
      }
      router.refresh();
    });
  };

  const upload = (file: File | undefined) => {
    if (!file) return;
    if (!LOGO_TYPES.includes(file.type)) {
      setError(t("logoUnsupported"));
      return;
    }
    if (file.size > LOGO_MAX_BYTES) {
      setError(t("logoTooLarge"));
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    run(() => uploadWorkspaceLogoAction(formData));
  };

  const { isDragging, dropProps } = useFileDrop({
    onFiles: (files) => upload(files[0]?.file),
    disabled: pending,
  });

  return (
    <SettingsRow
      title={t("logoTitle")}
      description={
        <>
          {t("logoDescription")}
          {workspace.logo_url && (
            <Button
              type="button"
              variant="ghost"
              size="xs"
              className="-ml-1 mt-1.5 flex w-fit"
              disabled={pending}
              onClick={() => run(deleteWorkspaceLogoAction)}
            >
              {t("logoRemove")}
            </Button>
          )}
        </>
      }
      control="fill"
    >
      <WorkspaceIcon workspace={workspace} size={72} />
      <label
        {...dropProps}
        className={cn(
          "flex min-w-0 flex-1 cursor-pointer items-center gap-3 rounded-md border border-dashed px-3.5 py-3 transition-colors",
          isDragging
            ? "border-primary bg-primary/5"
            : error
              ? "border-destructive/50 hover:bg-muted/40"
              : "border-border hover:bg-muted/40",
          pending && "pointer-events-none opacity-60"
        )}
      >
        <input
          type="file"
          accept={LOGO_TYPES.join(",")}
          className="hidden"
          aria-label={t("logoUpload")}
          disabled={pending}
          onChange={(event) => {
            upload(event.target.files?.[0]);
            event.target.value = "";
          }}
        />
        <span
          className={cn(
            "grid h-8 w-8 shrink-0 place-items-center rounded-md border bg-background",
            isDragging
              ? "border-primary/30 text-primary"
              : "border-border text-muted-foreground"
          )}
        >
          {pending ? (
            <Loader2 className="h-4 w-4 animate-spin" />
          ) : (
            <Upload className="h-4 w-4" />
          )}
        </span>
        <span className="min-w-0">
          <span className="block text-xs font-medium text-foreground/80">
            {t.rich("logoDrop", {
              browse: (chunks) => (
                <span className="text-primary">{chunks}</span>
              ),
            })}
          </span>
          <span
            role={error ? "alert" : undefined}
            className={cn(
              "mt-0.5 block text-xs",
              error ? "text-destructive" : "text-muted-foreground"
            )}
          >
            {error ?? t("logoFormats")}
          </span>
        </span>
      </label>
    </SettingsRow>
  );
}
