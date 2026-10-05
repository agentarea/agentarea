"use client";

import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { zodResolver } from "@hookform/resolvers/zod";
import { FileText, FolderTree, MessageSquare } from "lucide-react";
import { Controller, useForm } from "react-hook-form";
import { z } from "zod";
import type { ProjectResponse } from "@/api/client/types.gen";
import { zProjectCreate } from "@/api/client/zod.gen";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Input } from "@/components/ui/input";
import { MarkdownTextarea } from "@/components/ui/markdown-textarea";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { createProjectAction, updateProjectAction } from "@/lib/server-actions";
import {
  toProjectFormValues,
  toProjectPayload,
  type ProjectFormValues,
} from "./projectContract";

/** The header's submit button targets the form by this id. */
export const PROJECT_FORM_ID = "project-form";

/** Tells the header button the form is saving (see `useFormSubmittingState`). */
function announceSubmitting(
  form: HTMLFormElement | null,
  isSubmitting: boolean
) {
  if (!form) return;
  if (isSubmitting) form.setAttribute("data-submitting", "true");
  else form.removeAttribute("data-submitting");
  form.dispatchEvent(
    new CustomEvent("form-submitting", { detail: { isSubmitting } })
  );
}

/**
 * Creates a project, or edits one when `project` is given — the same fields
 * either way, empty for a new project and filled in for an existing one. The
 * submit button lives in the page header.
 */
export default function ProjectForm({
  project,
}: {
  project?: ProjectResponse;
}) {
  const t = useTranslations("ProjectsPage.form");
  const tCommon = useTranslations("Common");
  const router = useWorkspaceRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const [formError, setFormError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  // The generated contract's limits over the form's plain strings (a blank
  // note becomes null in `toProjectPayload`); the name gets our own message.
  const schema = useMemo(
    () =>
      z.object({
        name: z.string().trim().min(1, t("nameRequired")).max(255),
        description: zProjectCreate.shape.description.unwrap().unwrap(),
        instructions: zProjectCreate.shape.instructions.unwrap().unwrap(),
      }),
    [t]
  );

  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<ProjectFormValues>({
    resolver: zodResolver(schema),
    defaultValues: toProjectFormValues(project),
  });

  const onSubmit = async (values: ProjectFormValues) => {
    setFormError(null);
    setSaved(false);
    announceSubmitting(formRef.current, true);
    let leaving = false;
    try {
      const payload = toProjectPayload(values);
      if (project) {
        const result = await updateProjectAction(project.id, payload);
        if (result.error) {
          setFormError(apiErrorMessage(result, t("saveFailed")));
          return;
        }
        setSaved(true);
        reset(values);
        // The name in the breadcrumb and the hero comes from the server.
        router.refresh();
      } else {
        const result = await createProjectAction(payload);
        const createdId = (result.data as { id?: string } | undefined)?.id;
        if (result.error || !createdId) {
          setFormError(apiErrorMessage(result, t("createFailed")));
          return;
        }
        // Keep the header button busy until the new project's page opens.
        leaving = true;
        router.push(`/projects/${createdId}`);
      }
    } catch (err) {
      console.error("Failed to save project", err);
      setFormError(
        `${project ? t("saveFailed") : t("createFailed")}: ${formatApiError(err)}`
      );
    } finally {
      if (!leaving) announceSubmitting(formRef.current, false);
    }
  };

  const errorText = (field: keyof ProjectFormValues) =>
    errors[field]?.message ? (
      <p id={`project-${field}-error`} role="alert" className="form-error">
        {errors[field]?.message}
      </p>
    ) : null;

  return (
    <form
      ref={formRef}
      id={PROJECT_FORM_ID}
      onSubmit={handleSubmit(onSubmit)}
      onChange={() => setSaved(false)}
      className="form-content mx-auto w-full max-w-4xl"
    >
      {formError && <FormError>{formError}</FormError>}
      {saved && (
        <p className="text-xs text-muted-foreground" role="status">
          {tCommon("saved")}
        </p>
      )}

      <div className="space-y-2">
        <FormLabel htmlFor="project-name" icon={FolderTree} required>
          {t("name")}
        </FormLabel>
        <Input
          id="project-name"
          {...register("name")}
          placeholder={t("namePlaceholder")}
          autoFocus={!project}
          aria-invalid={Boolean(errors.name)}
          aria-describedby={errors.name ? "project-name-error" : undefined}
        />
        {errorText("name")}
      </div>

      <div className="space-y-2">
        <FormLabel htmlFor="project-description" icon={FileText} optional>
          {t("description")}
        </FormLabel>
        <Textarea
          id="project-description"
          {...register("description")}
          placeholder={t("descriptionPlaceholder")}
          className="h-[100px] resize-none"
          aria-invalid={Boolean(errors.description)}
          aria-describedby={
            errors.description ? "project-description-error" : undefined
          }
        />
        {errorText("description")}
      </div>

      <div className="space-y-2">
        <FormLabel htmlFor="project-instructions" icon={MessageSquare} optional>
          {t("instructions")}
        </FormLabel>
        <Controller
          name="instructions"
          control={control}
          render={({ field }) => (
            <MarkdownTextarea
              id="project-instructions"
              value={field.value}
              onChange={(value) => {
                field.onChange(value);
                setSaved(false);
              }}
              placeholder={t("instructionsPlaceholder")}
              className="h-[200px] resize-none"
              aria-invalid={Boolean(errors.instructions)}
            />
          )}
        />
        {errorText("instructions")}
      </div>
    </form>
  );
}
