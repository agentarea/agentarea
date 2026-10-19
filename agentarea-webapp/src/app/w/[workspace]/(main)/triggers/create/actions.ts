"use server";

import { revalidatePath } from "next/cache";
import type { TriggerCreate, TriggerUpdate } from "@/api/client/types.gen";
import { zTriggerCreate, zTriggerUpdate } from "@/api/client/zod.gen";
import { createTrigger, updateTrigger } from "@/lib/api";
import { formatApiError } from "@/lib/api-errors";
import { requestWorkspacePath } from "@/lib/workspace-request";

export type TriggerFormState = {
  message: string;
  errors?: { [key: string]: string[] };
  success?: boolean;
  /** Set by create: the new trigger, so the form can open it. */
  triggerId?: string;
};

function parseTaskParameters(raw: string | null): {
  data?: Record<string, unknown>;
  error?: TriggerFormState;
} {
  if (!raw || !raw.trim()) {
    return {};
  }

  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {
        error: {
          message: "Invalid JSON in task parameters",
          errors: {
            task_parameters: ["Task parameters must be a JSON object"],
          },
        },
      };
    }

    return { data: parsed };
  } catch {
    return {
      error: {
        message: "Invalid JSON in task parameters",
        errors: { task_parameters: ["Invalid JSON format"] },
      },
    };
  }
}

function parseJsonObject(
  raw: string | null,
  field: string,
  label: string
): { data?: Record<string, unknown>; error?: TriggerFormState } {
  if (!raw || !raw.trim()) {
    return {};
  }

  try {
    const parsed = JSON.parse(raw);
    if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
      return {
        error: {
          message: `Invalid JSON in ${label}`,
          errors: { [field]: [`${label} must be a JSON object`] },
        },
      };
    }

    return { data: parsed };
  } catch {
    return {
      error: {
        message: `Invalid JSON in ${label}`,
        errors: { [field]: ["Invalid JSON format"] },
      },
    };
  }
}

/**
 * A stream trigger's session setting, as `SessionSetting` posts it; absent when
 * the form carries none, which leaves the source's default.
 */
function parseSession(formData: FormData): TriggerCreate["session"] {
  const keep = formData.get("session_continue");
  const idleTimeout = formData.get("session_idle_timeout");
  if (typeof keep !== "string" || typeof idleTimeout !== "string") {
    return undefined;
  }
  return { continue: keep === "true", idle_timeout: idleTimeout };
}

function buildTriggerCreate(formData: FormData): TriggerCreate {
  const trigger_type = formData.get("trigger_type") as string;
  const task_parameters_raw = formData.get("task_parameters") as string | null;
  const failure_threshold_raw = formData.get("failure_threshold") as string;

  const parsedTaskParameters = parseJsonObject(
    task_parameters_raw,
    "task_parameters",
    "task parameters"
  );
  if (parsedTaskParameters.error) {
    throw parsedTaskParameters.error;
  }

  const failure_threshold = failure_threshold_raw
    ? parseInt(failure_threshold_raw, 10)
    : undefined;

  const body: TriggerCreate = {
    name: formData.get("name") as string,
    description: (formData.get("description") as string) || "",
    trigger_type: trigger_type as TriggerCreate["trigger_type"],
    agent_id: formData.get("agent_id") as string,
    task_parameters: parsedTaskParameters.data,
    failure_threshold:
      failure_threshold && !isNaN(failure_threshold)
        ? failure_threshold
        : undefined,
  };

  if (trigger_type === "cron") {
    body.cron_expression = formData.get("cron_expression") as string;
    body.timezone = (formData.get("timezone") as string) || "UTC";
  } else if (trigger_type === "stream") {
    body.stream_id = formData.get("stream_id") as string;
    body.session = parseSession(formData);
  }

  return body;
}

export async function createTriggerAction(
  prevState: TriggerFormState,
  formData: FormData
): Promise<TriggerFormState> {
  let rawData: TriggerCreate;
  try {
    rawData = buildTriggerCreate(formData);
  } catch (error) {
    return error as TriggerFormState;
  }

  const validated = zTriggerCreate.safeParse(rawData);

  if (!validated.success) {
    const mappedErrors: { [key: string]: string[] } = {};
    for (const issue of validated.error.issues) {
      const path = issue.path.join(".");
      if (!mappedErrors[path]) {
        mappedErrors[path] = [];
      }
      mappedErrors[path].push(issue.message);
    }
    return {
      message: "Validation failed. Please check the fields.",
      errors: mappedErrors,
    };
  }

  try {
    const { data, error } = await createTrigger(validated.data);

    if (error) {
      const errorMessage = formatApiError(error);
      return {
        message: "Failed to create trigger",
        errors: { _form: [`API error: ${errorMessage}`] },
      };
    }

    if (data) {
      revalidatePath(await requestWorkspacePath("/triggers"));
      return {
        message: "Trigger created successfully!",
        success: true,
        triggerId: data.id,
      };
    }
  } catch (err) {
    return {
      message: "Failed to create trigger",
      errors: {
        _form: [
          `Unexpected error: ${err instanceof Error ? err.message : "Unknown error"}`,
        ],
      },
    };
  }

  return {
    message: "Unknown error occurred",
    errors: { _form: ["Unknown error occurred"] },
  };
}

export async function updateTriggerAction(
  prevState: TriggerFormState,
  formData: FormData
): Promise<TriggerFormState> {
  const id = formData.get("id") as string;
  if (!id) {
    return {
      message: "Trigger ID is required",
      errors: { _form: ["Missing trigger ID"] },
    };
  }

  const name = formData.get("name") as string;
  const trigger_type = formData.get("trigger_type") as string;
  const task_parameters_raw = formData.get("task_parameters") as string;
  const failure_threshold_raw = formData.get("failure_threshold") as string;

  const parsedTaskParameters = parseTaskParameters(task_parameters_raw);
  if (parsedTaskParameters.error) return parsedTaskParameters.error;
  const task_parameters = parsedTaskParameters.data;

  // Parse failure threshold
  const failure_threshold = failure_threshold_raw
    ? Number(failure_threshold_raw)
    : undefined;

  const updateBody: TriggerUpdate = {
    name,
    description: formData.get("description") as string | null,
    agent_id: formData.get("agent_id") as string | null,
    task_parameters,
    failure_threshold,
  };

  if (trigger_type === "cron") {
    const cronExpr = formData.get("cron_expression") as string;
    const timezone = formData.get("timezone") as string;
    if (cronExpr !== null) updateBody.cron_expression = cronExpr;
    if (timezone !== null) updateBody.timezone = timezone;
  }

  if (trigger_type === "stream") {
    updateBody.session = parseSession(formData);
  }

  const validated = zTriggerUpdate.safeParse(updateBody);
  if (!validated.success) {
    return {
      message: "Validation failed. Please check the fields.",
      errors: validated.error.flatten().fieldErrors,
    };
  }

  try {
    const { data, error } = await updateTrigger(id, validated.data);

    if (error) {
      return {
        message: "Failed to update trigger",
        errors: { _form: [`API error: ${formatApiError(error)}`] },
      };
    }

    if (data) {
      revalidatePath(await requestWorkspacePath("/triggers"));
      revalidatePath(await requestWorkspacePath(`/triggers/${id}`));
      return {
        message: "Trigger updated successfully!",
        success: true,
      };
    }
  } catch (err) {
    return {
      message: "Failed to update trigger",
      errors: {
        _form: [
          `Unexpected error: ${err instanceof Error ? err.message : "Unknown error"}`,
        ],
      },
    };
  }

  return {
    message: "Unknown error occurred",
    errors: { _form: ["Unknown error occurred"] },
  };
}
