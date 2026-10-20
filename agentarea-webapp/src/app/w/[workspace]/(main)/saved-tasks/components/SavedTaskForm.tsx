"use client";

import { useActionState, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import type {
  AgentResponse,
  TaskDefinitionResponse,
} from "@/api/client/types.gen";
import { AgentSelect } from "@/components/AgentSelect";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { saveSavedTaskAction, type SavedTaskFormState } from "../actions";

export const SAVED_TASK_FORM_ID = "saved-task-form";

export function SavedTaskForm({
  agents,
  initialData,
}: {
  agents: AgentResponse[];
  initialData?: TaskDefinitionResponse;
}) {
  const t = useTranslations("SavedTasksPage.form");
  const router = useWorkspaceRouter();
  const [state, formAction, isPending] = useActionState<
    SavedTaskFormState,
    FormData
  >(saveSavedTaskAction, {});
  const [agentId, setAgentId] = useState(initialData?.agent_id ?? "");

  // Mirror pending state onto the form element so the header controls can
  // render the submit button's loading state (see useFormSubmittingState).
  useEffect(() => {
    const form = document.getElementById(SAVED_TASK_FORM_ID);
    if (!form) return;
    form.setAttribute("data-submitting", String(isPending));
    form.dispatchEvent(
      new CustomEvent("form-submitting", {
        detail: { isSubmitting: isPending },
      })
    );
  }, [isPending]);

  useEffect(() => {
    if (state.definitionId) router.push(`/saved-tasks/${state.definitionId}`);
  }, [state.definitionId, router]);

  const error = (field: string) =>
    state.errors?.[field] && (
      <p className="text-sm text-destructive">{state.errors[field][0]}</p>
    );

  return (
    <form
      id={SAVED_TASK_FORM_ID}
      action={formAction}
      className="mx-auto grid w-full max-w-[1120px] gap-6 pb-10 pt-2"
    >
      {initialData && <input type="hidden" name="id" value={initialData.id} />}
      {error("_form")}
      <div className="grid gap-2">
        <Label htmlFor="name" className="sr-only">
          {t("name")}
        </Label>
        <Input
          id="name"
          name="name"
          variant="title"
          placeholder={t("namePlaceholder")}
          defaultValue={initialData?.name ?? ""}
          required
        />
        {error("name")}
      </div>
      <div className="grid gap-2 sm:max-w-sm">
        <FormLabel htmlFor="agent_id" required>
          {t("agent")}
        </FormLabel>
        <AgentSelect
          id="agent_id"
          name="agent_id"
          agents={agents}
          value={agentId}
          onChange={setAgentId}
          placeholder={t("selectAgent")}
        />
        {error("agent_id")}
      </div>
      <div className="grid gap-2">
        <FormLabel htmlFor="description" required>
          {t("description")}
        </FormLabel>
        <Textarea
          id="description"
          name="description"
          variant="document"
          rows={8}
          placeholder={t("descriptionPlaceholder")}
          defaultValue={initialData?.description ?? ""}
          required
        />
        {error("description")}
      </div>
      <div className="grid gap-2">
        <FormLabel htmlFor="parameters" optional>
          {t("parameters")}
        </FormLabel>
        <p className="text-xs text-muted-foreground">{t("parametersHint")}</p>
        <Textarea
          id="parameters"
          name="parameters"
          rows={5}
          className="font-mono text-xs"
          defaultValue={JSON.stringify(initialData?.parameters ?? {}, null, 2)}
        />
        {error("parameters")}
      </div>
    </form>
  );
}
