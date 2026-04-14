"use server";

import { z } from "zod";
import { createTrigger, updateTrigger } from "@/lib/api";

const TriggerCreateSchema = z.object({
  name: z.string().min(1, "Name is required"),
  trigger_type: z.enum(["cron", "webhook"], {
    required_error: "Trigger type is required",
  }),
  agent_id: z.string().uuid("Agent is required"),
  config: z.record(z.unknown()),
  task_parameters: z.record(z.unknown()).optional(),
  failure_threshold: z.number().int().positive().optional(),
});

const TriggerUpdateSchema = TriggerCreateSchema.partial().extend({
  id: z.string().uuid(),
});

export type TriggerFormState = {
  message: string;
  errors?: { [key: string]: string[] };
  success?: boolean;
};

function buildConfig(formData: FormData): Record<string, any> {
  const trigger_type = formData.get("trigger_type") as string;
  const data_extractor = formData.get("data_extractor") as string | null;

  // Collect channel credentials from credential_* form fields
  const channel_credentials: Record<string, string> = {};
  for (const [key, value] of formData.entries()) {
    if (key.startsWith("credential_") && value) {
      channel_credentials[key.replace("credential_", "")] = value as string;
    }
  }

  let config: Record<string, any> = {};
  if (trigger_type === "cron") {
    config = {
      cron_expression: formData.get("cron_expression") as string,
      timezone: (formData.get("timezone") as string) || "UTC",
    };
    if (data_extractor) {
      config.data_extractor = data_extractor;
    }
  } else if (trigger_type === "webhook") {
    const webhook_type = formData.get("webhook_type") as string;
    const methods: string[] = [];
    ["GET", "POST", "PUT", "PATCH", "DELETE"].forEach((method) => {
      if (formData.get(`method_${method}`) === "on") {
        methods.push(method);
      }
    });
    config = {
      webhook_type: webhook_type || "generic",
      allowed_methods: methods.length > 0 ? methods : ["POST"],
    };
  }

  if (Object.keys(channel_credentials).length > 0) {
    config.channel_credentials = channel_credentials;
  }

  return config;
}

export async function createTriggerAction(
  prevState: TriggerFormState,
  formData: FormData
): Promise<TriggerFormState> {
  const name = formData.get("name") as string;
  const trigger_type = formData.get("trigger_type") as string;
  const agent_id = formData.get("agent_id") as string;
  const task_parameters_raw = formData.get("task_parameters") as string;
  const failure_threshold_raw = formData.get("failure_threshold") as string;

  const config = buildConfig(formData);

  // Parse task parameters
  let task_parameters: Record<string, any> | undefined;
  if (task_parameters_raw && task_parameters_raw.trim()) {
    try {
      task_parameters = JSON.parse(task_parameters_raw);
    } catch {
      return {
        message: "Invalid JSON in task parameters",
        errors: { task_parameters: ["Invalid JSON format"] },
      };
    }
  }

  // Parse failure threshold
  const failure_threshold = failure_threshold_raw
    ? parseInt(failure_threshold_raw, 10)
    : undefined;

  const rawData = {
    name,
    trigger_type,
    agent_id,
    config,
    task_parameters,
    failure_threshold:
      failure_threshold && !isNaN(failure_threshold)
        ? failure_threshold
        : undefined,
  };

  const validated = TriggerCreateSchema.safeParse(rawData);

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

  // Parse task parameters
  let task_parameters: Record<string, any> | undefined;
  if (task_parameters_raw && task_parameters_raw.trim()) {
    try {
      task_parameters = JSON.parse(task_parameters_raw);
    } catch {
      return {
        message: "Invalid JSON in task parameters",
        errors: { task_parameters: ["Invalid JSON format"] },
      };
    }
  }

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
