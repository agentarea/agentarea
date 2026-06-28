"use server";

import type { TriggerCreate } from "@/api/client/types.gen";
import { zTriggerCreate } from "@/api/client/zod.gen";
import { createTrigger, updateTrigger } from "@/lib/api";

export type TriggerFormState = {
  message: string;
  errors?: { [key: string]: string[] };
  success?: boolean;
};

function parseTaskParameters(raw: string | null): {
  data?: Record<string, any>;
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
          errors: { task_parameters: ["Task parameters must be a JSON object"] },
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

function parseStringArray(raw: string | null): string[] | undefined {
  if (!raw || !raw.trim()) {
    return undefined;
  }

  try {
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed)
      ? parsed.filter((value): value is string => typeof value === "string")
      : undefined;
  } catch {
    return undefined;
  }
}

function buildTriggerCreate(formData: FormData): TriggerCreate {
  const trigger_type = formData.get("trigger_type") as string;
  const data_extractor = formData.get("data_extractor") as string | null;
  const task_parameters_raw = formData.get("task_parameters") as string | null;
  const failure_threshold_raw = formData.get("failure_threshold") as string;

  const channel_credentials: Record<string, string> = {};
  for (const [key, value] of formData.entries()) {
    if (key.startsWith("credential_") && value) {
      channel_credentials[key.replace("credential_", "")] = value as string;
    }
  }

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
    if (data_extractor) {
      body.data_extractor = data_extractor;
    }
  } else if (trigger_type === "webhook") {
    const webhook_type = formData.get("webhook_type") as string;
    const methods: string[] = [];
    ["GET", "POST", "PUT", "PATCH", "DELETE"].forEach((method) => {
      if (formData.get(`method_${method}`) === "on") {
        methods.push(method);
      }
    });
    body.webhook_type = webhook_type || "generic";
    body.allowed_methods = methods.length > 0 ? methods : ["POST"];
    body.event_types = parseStringArray(formData.get("event_types") as string);
  }

  if (Object.keys(channel_credentials).length > 0) {
    body.channel_credentials = channel_credentials;
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
    const { data, error } = await createTrigger(validated.data as any);

    if (error) {
      const errorMessage = (error as any)?.detail?.[0]?.msg || "Unknown error";
      return {
        message: "Failed to create trigger",
        errors: { _form: [`API error: ${errorMessage}`] },
      };
    }

    if (data) {
      return {
        message: "Trigger created successfully!",
        success: true,
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
    ? parseInt(failure_threshold_raw, 10)
    : undefined;

  // Build flat update body matching TriggerUpdateRequest schema
  const updateBody: Record<string, any> = { name };

  if (trigger_type === "cron") {
    const cronExpr = formData.get("cron_expression") as string;
    const timezone = formData.get("timezone") as string;
    if (cronExpr) updateBody.cron_expression = cronExpr;
    if (timezone) updateBody.timezone = timezone;
  }

  if (task_parameters) updateBody.task_parameters = task_parameters;
  if (failure_threshold && !isNaN(failure_threshold)) {
    updateBody.failure_threshold = failure_threshold;
  }

  try {
    const { data, error } = await updateTrigger(id, updateBody);

    if (error) {
      const detail = (error as any)?.detail;
      const errorMessage =
        typeof detail === "string"
          ? detail
          : Array.isArray(detail)
            ? detail[0]?.msg || JSON.stringify(detail)
            : "Unknown error";
      return {
        message: "Failed to update trigger",
        errors: { _form: [`API error: ${errorMessage}`] },
      };
    }

    if (data) {
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
