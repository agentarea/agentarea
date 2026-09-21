"use server";

import { revalidatePath } from "next/cache";
import { z } from "zod";
import type { TriggerCreate, TriggerUpdate } from "@/api/client/types.gen";
import {
  zGetCatalogV1TriggersCatalogGetResponse,
  zTriggerCreate,
  zTriggerUpdate,
} from "@/api/client/zod.gen";
import { createTrigger, listTriggerCatalog, updateTrigger } from "@/lib/api";
import { formatApiError } from "@/lib/api-errors";

export type TriggerFormState = {
  message: string;
  errors?: { [key: string]: string[] };
  success?: boolean;
};

const zTriggerCatalogEntry = z.object({
  id: z.string(),
  name: z.string(),
  /** Asset id kept for reference; the UI draws `icon_url`, not this. */
  icon: z.string(),
  /** Resolved by the API. Declared here or zod strips it off the entry. */
  icon_url: z.string().nullish(),
  description: z.string(),
  kind: z.enum(["messaging", "event", "schedule"]),
  backend_type: z.enum(["cron", "webhook", "polling"]),
  webhook_type: z.string().optional(),
  default_methods: z.array(z.string()).optional(),
  default_cron: z.string().optional(),
  data_extractor: z.string().optional(),
  credential_fields: z
    .array(
      z.object({
        key: z.string(),
        label: z.string(),
        placeholder: z.string(),
      })
    )
    .optional(),
  events: z.array(z.string()).optional(),
});

export type TriggerCatalogEntry = z.infer<typeof zTriggerCatalogEntry>;

export async function listTriggerCatalogAction(): Promise<
  TriggerCatalogEntry[]
> {
  const { data, error } = await listTriggerCatalog();
  if (error || !data) {
    throw new Error("Failed to load trigger catalog");
  }
  const records = zGetCatalogV1TriggersCatalogGetResponse.parse(data);
  // Per entry, not over the array: the catalog grows server-side, and parsing it
  // whole meant one channel this build does not know about emptied the picker.
  const entries: TriggerCatalogEntry[] = [];
  for (const record of records) {
    const parsed = zTriggerCatalogEntry.safeParse(record);
    if (parsed.success) {
      entries.push(parsed.data);
    } else {
      console.warn(
        `Skipping trigger catalog entry the UI cannot render: ${JSON.stringify(record)}`,
        parsed.error.flatten().fieldErrors
      );
    }
  }
  if (entries.length === 0 && records.length > 0) {
    throw new Error("No trigger catalog entry could be read");
  }
  return entries;
}

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

function parseChannelCredentials(formData: FormData): {
  data: NonNullable<TriggerCreate["channel_credentials"]>;
  /** Credential fields the form posted empty, named by their form key. */
  missing: string[];
  error?: TriggerFormState;
} {
  const data: NonNullable<TriggerCreate["channel_credentials"]> = {};
  const missing: string[] = [];
  for (const [key, value] of formData.entries()) {
    if (typeof value !== "string") continue;
    if (!value) {
      if (key.startsWith("credential_secret_")) missing.push(key);
      continue;
    }
    if (key.startsWith("credential_secret_")) {
      const secretId = z.string().uuid().safeParse(value);
      if (!secretId.success) {
        return {
          data: {},
          missing: [],
          error: {
            message: "Invalid secret selection",
            errors: { [key]: ["Select a workspace secret"] },
          },
        };
      }
      data[key.slice("credential_secret_".length)] = {
        secret_id: secretId.data,
      };
    } else if (key.startsWith("credential_")) {
      data[key.slice("credential_".length)] = value;
    }
  }
  return { data, missing };
}

function buildTriggerCreate(formData: FormData): TriggerCreate {
  const trigger_type = formData.get("trigger_type") as string;
  const data_extractor = formData.get("data_extractor") as string | null;
  const task_parameters_raw = formData.get("task_parameters") as string | null;
  const failure_threshold_raw = formData.get("failure_threshold") as string;

  const credentials = parseChannelCredentials(formData);
  if (credentials.error) throw credentials.error;
  // A channel that extracts its payload cannot run without its credential, and
  // the picker is a combobox, so the browser no longer blocks the submit.
  if (data_extractor && credentials.missing.length > 0) {
    const missingCredentials: TriggerFormState = {
      message: "Validation failed. Please check the fields.",
      errors: Object.fromEntries(
        credentials.missing.map((key) => [key, ["Select a workspace secret"]])
      ),
    };
    throw missingCredentials;
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
    if (data_extractor) {
      body.data_extractor = data_extractor;
    }
  } else if (trigger_type === "webhook") {
    const webhook_type = formData.get("webhook_type") as string;
    const methods: string[] = [];
    ["GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"].forEach(
      (method) => {
        if (formData.get(`method_${method}`) === "on") {
          methods.push(method);
        }
      }
    );
    body.webhook_type = webhook_type || "generic";
    body.allowed_methods = methods.length > 0 ? methods : ["POST"];
    body.event_types = parseStringArray(formData.get("event_types") as string);
  }

  if (Object.keys(credentials.data).length > 0) {
    body.channel_credentials = credentials.data;
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
    const { data, error } = await createTrigger(
      validated.data as unknown as Parameters<typeof createTrigger>[0]
    );

    if (error) {
      const errorMessage = formatApiError(error);
      return {
        message: "Failed to create trigger",
        errors: { _form: [`API error: ${errorMessage}`] },
      };
    }

    if (data) {
      revalidatePath("/triggers");
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

  if (trigger_type === "webhook") {
    updateBody.allowed_methods = [
      "GET",
      "POST",
      "PUT",
      "PATCH",
      "DELETE",
      "HEAD",
      "OPTIONS",
    ].filter((method) => formData.get(`method_${method}`) === "on");
    updateBody.event_types = parseStringArray(
      formData.get("event_types") as string
    );
  }

  const credentials = parseChannelCredentials(formData);
  if (credentials.error) return credentials.error;
  if (Object.keys(credentials.data).length > 0) {
    updateBody.channel_credentials = credentials.data;
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
      revalidatePath("/triggers");
      revalidatePath(`/triggers/${id}`);
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
