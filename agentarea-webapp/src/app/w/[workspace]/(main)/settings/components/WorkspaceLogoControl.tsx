"use client";

import { useRef, useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { Loader2, Trash2, Upload } from "lucide-react";
import { Button } from "@/components/ui/button";
import { WorkspaceIcon } from "@/components/WorkspaceIcon";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import type { Workspace } from "@/lib/workspaces";
import { deleteWorkspaceLogoAction, uploadWorkspaceLogoAction } from "../actions";

// The API's limit; checked here so an oversized file never leaves the browser.
const LOGO_MAX_BYTES = 1024 * 1024;

export default function WorkspaceLogoControl({
  workspace,
}: {
  workspace: Workspace;
}) {
  const t = useTranslations("SettingsPage.workspace");
  const router = useWorkspaceRouter();
  const inputRef = useRef<HTMLInputElement>(null);
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

  const upload = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    if (file.size > LOGO_MAX_BYTES) {
      setError(t("logoTooLarge"));
      return;
    }
    const formData = new FormData();
    formData.append("file", file);
    run(() => uploadWorkspaceLogoAction(formData));
  };

  return (
    <div className="flex flex-col items-start gap-2 md:items-end">
      <div className="flex items-center gap-2">
        <WorkspaceIcon workspace={workspace} size={32} />
        <Button
          onClick={() => inputRef.current?.click()}
          variant="outline"
          size="sm"
          className="gap-1"
          disabled={pending}
        >
          {pending ? <Loader2 className="animate-spin" /> : <Upload />}
          {t("logoUpload")}
        </Button>
        {workspace.logo_url && (
          <Button
            onClick={() => run(deleteWorkspaceLogoAction)}
            variant="ghost"
            size="sm"
            className="gap-1"
            disabled={pending}
          >
            <Trash2 />
            {t("logoRemove")}
          </Button>
        )}
      </div>
      <input
        ref={inputRef}
        type="file"
        accept="image/png,image/jpeg,image/webp"
        className="hidden"
        aria-label={t("logoUpload")}
        onChange={upload}
      />
      {error && (
        <p role="alert" className="max-w-sm text-xs text-destructive">
          {error}
        </p>
      )}
    </div>
  );
}
