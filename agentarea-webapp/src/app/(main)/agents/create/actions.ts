"use server";

import type { AgentCreate } from "@/api/client/types.gen";
import { zAgentCreate } from "@/api/client/zod.gen";
import { createAgent } from "@/lib/api";
import { toAgentCreate } from "../shared/agentContract";
import type { AgentFormValues } from "./types";

// Form-state contract consumed by AgentForm (and the edit form): drives error
// display and the "success" / created-id detection. Input to the action is the
// typed RHF object (AgentFormValues) directly — no FormData round-trip.
export interface AddAgentFormState {
  message: string;
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
    events_config?: {
      events?: Array<{
        event_type: string;
        config?: Record<string, unknown> | null;
        enabled?: boolean;
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
  // Map the UI form to the backend contract, then validate against the
  // GENERATED schema. zAgentCreate is generated from the backend OpenAPI spec,
  // so any drift between frontend and backend fails here at the boundary
  // instead of silently producing a malformed request.
  const body = toAgentCreate(input);
  const parsed = zAgentCreate.safeParse(body);

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

  try {
    const { data, error } = await createAgent(parsed.data as AgentCreate);

    if (error) {
      const apiErr = error as { message?: string; detail?: Array<{ msg: string }> };
      const errorMessage =
        apiErr?.message ||
        apiErr?.detail?.[0]?.msg ||
        "Unknown error";
      return {
        message: "Failed to create agent",
        errors: { _form: [`API error: ${errorMessage}`] },
        fieldValues: input,
      };
    }

    if (data) {
      return {
        message: "Agent created successfully!",
        fieldValues: { ...input, id: data.id },
      };
    }
  } catch (err) {
    return {
      message: "Failed to create agent",
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
