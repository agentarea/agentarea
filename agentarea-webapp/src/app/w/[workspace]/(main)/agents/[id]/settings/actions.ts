"use server";

import type { AgentUpdate } from "@/api/client/types.gen";
import { getTranslations } from "next-intl/server";
import { zAgentUpdate } from "@/api/client/zod.gen";
import { apiErrorMessage } from "@/lib/api-errors";
import { updateAgent as updateAgentAPI } from "@/lib/api";
import type { AddAgentFormState } from "../../create/actions";
import type { AgentFormValues } from "../../create/types";
import { toAgentUpdate } from "../../shared/agentContract";

export async function updateAgentSettings(
  agentId: string,
  input: AgentFormValues
): Promise<AddAgentFormState> {
  const t = await getTranslations("AgentsPage.form");
  const parsed = zAgentUpdate.safeParse(toAgentUpdate(input));

  if (!parsed.success) {
    const errors: { [key: string]: string[] } = {};
    for (const issue of parsed.error.issues) {
      const path = issue.path.join(".") || "_form";
      (errors[path] ??= []).push(issue.message);
    }
    return {
      ok: false,
      message: t("validationFailed"),
      errors,
      fieldValues: input,
    };
  }

  const result = await updateAgentAPI(agentId, parsed.data as AgentUpdate);

  if (result.error || !result.data) {
    const message = apiErrorMessage(result, t("saveFailed"));
    return {
      ok: false,
      message,
      errors: { _form: [message] },
      fieldValues: input,
    };
  }

  return {
    ok: true,
    fieldValues: input,
  };
}
