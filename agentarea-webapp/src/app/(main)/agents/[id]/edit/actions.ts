"use server";

import type { AgentUpdate } from "@/api/client/types.gen";
import { z } from "zod";
import { zAgentUpdate } from "@/api/client/zod.gen";
import { updateAgent as updateAgentAPI } from "@/lib/api";
import type { AddAgentFormState } from "../../create/actions";
import type { AgentFormValues } from "../../create/types";
import { toAgentUpdate } from "../../shared/agentContract";

type UpdateAgentInput = AgentFormValues & {
  id: string;
  skill_ids?: string[] | null;
};

function mapZodErrors(error: z.ZodError): { [key: string]: string[] } {
  const mappedErrors: { [key: string]: string[] } = {};
  for (const issue of error.issues) {
    const path = issue.path.join(".") || "_form";
    (mappedErrors[path] ??= []).push(issue.message);
  }
  return mappedErrors;
}

export async function updateAgent(
  _prevState: AddAgentFormState,
  input: UpdateAgentInput
): Promise<AddAgentFormState> {
  const id = z.string().uuid("Invalid agent ID").safeParse(input.id);
  if (!id.success) {
    return {
      message: "Validation failed. Please check the fields.",
      errors: mapZodErrors(id.error),
      fieldValues: input,
    };
  }

  const body = toAgentUpdate(input, input.skill_ids);
  const validated = zAgentUpdate.safeParse(body);

  if (!validated.success) {
    return {
      message: "Validation failed. Please check the fields.",
      errors: mapZodErrors(validated.error),
      fieldValues: input,
    };
  }

  try {
    const { data, error } = await updateAgentAPI(
      id.data,
      validated.data as AgentUpdate
    );

    if (error) {
      const apiErr = error as { message?: string; detail?: Array<{ msg: string }> };
      const errorMessage =
        apiErr?.message ||
        apiErr?.detail?.[0]?.msg ||
        "Unknown error";
      return {
        message: "Failed to update agent",
        errors: { _form: [`API error: ${errorMessage}`] },
        fieldValues: input,
      };
    }

    if (data) {
      return {
        message: "Agent updated successfully!",
        fieldValues: input,
      };
    }
  } catch (err) {
    return {
      message: "Failed to update agent",
      errors: {
        _form: [
          `Unexpected error: ${err instanceof Error ? err.message : "Unknown error"}`,
        ],
      },
      fieldValues: input,
    };
  }

  return {
    message: "Unknown error occurred",
    errors: { _form: ["Unknown error occurred"] },
    fieldValues: input,
  };
}
