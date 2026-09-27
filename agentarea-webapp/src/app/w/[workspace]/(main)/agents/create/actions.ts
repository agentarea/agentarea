"use server";

import type { AgentCreateRequest } from "@/api/client/types.gen";
import { getTranslations } from "next-intl/server";
import { zAgentCreateRequest } from "@/api/client/zod.gen";
import { createAgent } from "@/lib/api";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { toAgentCreate } from "../shared/agentContract";
import type { AgentFormValues } from "./types";

// Form-state contract consumed by AgentForm (and the edit form): drives error
// display and the created-id detection. Input to the action is the
// typed RHF object (AgentFormValues) directly — no FormData round-trip.
export interface AddAgentFormState {
  ok: boolean;
  message?: string;
  errors?: { [key: string]: string[] };
  fieldValues?: {
    name?: string;
    description?: string;
    instruction?: string;
    model_id?: string;
    tools_config?: {
      mcp_server_configs?: Array<{
        mcp_server_id: string;
        allowed_tools?: Array<{
          tool_name: string;
          requires_user_confirmation?: boolean;
        }> | null;
      }> | null;
      builtin_tools?: Array<{
        tool_name: string;
        requires_user_confirmation?: boolean;
        enabled?: boolean;
        disabled_methods?: Record<string, boolean>;
      }> | null;
      openapi_configs?: Array<{
        openapi_connection_id: string;
        openapi_connection_name?: string;
        allowed_tools?: string[] | null;
        load_mode?: "explicit" | "searchable";
      }> | null;
    } | null;
    planning?: boolean;
    a2ui_enabled?: boolean;
    skill_ids?: string[] | null;
    id?: string;
  };
}

export async function addAgent(
  input: AgentFormValues
): Promise<AddAgentFormState> {
  const t = await getTranslations("AgentsPage.form");
  // Map the UI form to the backend contract, then validate against the
  // GENERATED schema. zAgentCreateRequest is generated from the backend OpenAPI spec,
  // so any drift between frontend and backend fails here at the boundary
  // instead of silently producing a malformed request.
  const body = toAgentCreate(input);
  const parsed = zAgentCreateRequest.safeParse(body);

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

  try {
    const result = await createAgent(parsed.data as AgentCreateRequest);

    if (result.error || !result.data) {
      const message = apiErrorMessage(result, t("createFailed"));
      return {
        ok: false,
        message,
        errors: { _form: [message] },
        fieldValues: input,
      };
    }

    return {
      ok: true,
      fieldValues: { ...input, id: result.data.id },
    };
  } catch (err) {
    console.error("Failed to create agent", err);
    const message = `${t("createFailed")}: ${formatApiError(err)}`;
    return {
      ok: false,
      message,
      errors: { _form: [message] },
      fieldValues: input,
    };
  }
}
