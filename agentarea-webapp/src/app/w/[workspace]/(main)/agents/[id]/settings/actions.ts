"use server";

import type { AgentUpdate } from "@/api/client/types.gen";
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
  const parsed = zAgentUpdate.safeParse(toAgentUpdate(input));

  if (!parsed.success) {
    const errors: { [key: string]: string[] } = {};
    for (const issue of parsed.error.issues) {
      const path = issue.path.join(".") || "_form";
      (errors[path] ??= []).push(issue.message);
    }
    return {
      message: "Validation failed. Please check the fields.",
      errors,
      fieldValues: input,
    };
  }

  const result = await updateAgentAPI(agentId, parsed.data as AgentUpdate);

  if (!result.data) {
    return {
      message: "Failed to update agent",
      errors: { _form: [apiErrorMessage(result, "Failed to update agent")] },
      fieldValues: input,
    };
  }

  return {
    message: "Agent updated successfully!",
    fieldValues: input,
  };
}
