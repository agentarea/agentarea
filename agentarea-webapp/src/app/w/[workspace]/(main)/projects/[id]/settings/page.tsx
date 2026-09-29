"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { notFound, useParams } from "next/navigation";
import { Loader2 } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Button } from "@/components/ui/button";
import EmptyState from "@/components/EmptyState";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { FormSkeleton } from "@/components/Skeleton";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import {
  apiErrorMessage,
  formatApiError,
  isApiNotFound,
} from "@/lib/api-errors";
import { getProjectAction, updateProjectAction } from "@/lib/server-actions";
import type { ProjectResponse } from "@/api/client/types.gen";

export default function ProjectSettingsPage() {
  const params = useParams();
  const projectId = params.id as string;
  const router = useWorkspaceRouter();
  const t = useTranslations("ProjectSettingsPage");
  const tCommon = useTranslations("Common");

  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [nameError, setNameError] = useState<string | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [instructions, setInstructions] = useState("");

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await getProjectAction(projectId);
      if (isApiNotFound(result)) {
        setMissing(true);
        return;
      }
      if (result.error || !result.data) {
        setLoadError(apiErrorMessage(result, t("loadFailed")));
        return;
      }
      const project = result.data as ProjectResponse;
      setName(project.name || "");
      setDescription(project.description || "");
      setInstructions(project.instructions || "");
    } catch (err) {
      console.error("Failed to load project settings", err);
      setLoadError(`${t("loadFailed")}: ${formatApiError(err)}`);
    } finally {
      setLoading(false);
    }
  }, [projectId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  const edited = () => {
    setSaved(false);
    setError(null);
  };

  const handleSave = async (e: React.FormEvent) => {
    e.preventDefault();
    setSaved(false);
    setError(null);

    if (!name.trim()) {
      setNameError(t("nameRequired"));
      return;
    }

    setSaving(true);
    try {
      const result = await updateProjectAction(projectId, {
        name: name.trim(),
        description: description.trim() || null,
        instructions: instructions.trim() || null,
      });

      if (result.error) {
        setError(apiErrorMessage(result, t("saveFailed")));
        return;
      }

      setSaved(true);
      // The breadcrumb comes from the server layout.
      router.refresh();
    } catch (err) {
      console.error("Failed to save project settings", err);
      setError(`${t("saveFailed")}: ${formatApiError(err)}`);
    } finally {
      setSaving(false);
    }
  };

  if (missing) notFound();

  if (loading) {
    return <FormSkeleton className="p-6 lg:max-w-xl" fields={3} />;
  }

  if (loadError) {
    return (
      <EmptyState
        title={t("loadFailed")}
        description={loadError}
        action={{ label: tCommon("retry"), onClick: () => void load() }}
      />
    );
  }

  return (
    <div className="p-6">
      <form id="project-settings-form" onSubmit={handleSave} className="space-y-4 lg:max-w-xl">
        {error && <FormError>{error}</FormError>}
        <div className="grid gap-2">
          <FormLabel htmlFor="settings-name" required>
            {t("name")}
          </FormLabel>
          <Input
            id="settings-name"
            value={name}
            onChange={(e) => {
              setName(e.target.value);
              setNameError(null);
              edited();
            }}
            aria-invalid={Boolean(nameError)}
            aria-describedby={nameError ? "settings-name-error" : undefined}
          />
          {nameError && (
            <p id="settings-name-error" role="alert" className="form-error">
              {nameError}
            </p>
          )}
        </div>
        <div className="grid gap-2">
          <FormLabel htmlFor="settings-description" required={false}>
            {t("description")}
          </FormLabel>
          <Textarea
            id="settings-description"
            value={description}
            onChange={(e) => {
              setDescription(e.target.value);
              edited();
            }}
            rows={3}
          />
        </div>
        <div className="grid gap-2">
          <FormLabel htmlFor="settings-instructions" required={false}>
            {t("instructions")}
          </FormLabel>
          <Textarea
            id="settings-instructions"
            value={instructions}
            onChange={(e) => {
              setInstructions(e.target.value);
              edited();
            }}
            rows={5}
          />
        </div>
        <div className="flex items-center justify-end gap-3">
          {saved && (
            <span className="text-xs text-muted-foreground" role="status">
              {tCommon("saved")}
            </span>
          )}
          <Button type="submit" size="xs" disabled={saving}>
            {saving ? <Loader2 className="mr-2 animate-spin" /> : null}
            {tCommon("saveChanges")}
          </Button>
        </div>
      </form>
    </div>
  );
}
