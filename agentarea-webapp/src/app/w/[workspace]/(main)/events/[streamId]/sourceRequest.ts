import type {
  SecretRef,
  StreamSourceTypeResponse,
  WebhookSourceCreate,
} from "@/api/client/types.gen";

/** What the add-source form holds: a picked secret id per credential, text per setting. */
export interface SourceFormValues {
  secrets: Record<string, string>;
  settings: Record<string, string>;
}

/**
 * The create body for a source of `type`: each picked secret by reference,
 * each setting trimmed, and anything blank or belonging to another type left
 * out — a blank optional secret is one the platform issues.
 */
export function toSourceRequest(
  type: StreamSourceTypeResponse,
  values: SourceFormValues
): WebhookSourceCreate {
  const credentials: Record<string, SecretRef> = {};
  for (const field of type.credentials) {
    const secretId = values.secrets[field.key]?.trim();
    if (secretId) credentials[field.key] = { secret_id: secretId };
  }
  const config: Record<string, string> = {};
  for (const field of type.config ?? []) {
    const value = values.settings[field.key]?.trim();
    if (value) config[field.key] = value;
  }
  return { webhook_type: type.webhook_type, credentials, config };
}

/** Keys of the required fields of `type` that are still blank. */
export function missingSourceFields(
  type: StreamSourceTypeResponse,
  values: SourceFormValues
): string[] {
  const blank = (value: string | undefined) => !value?.trim();
  return [
    ...type.credentials
      .filter((f) => f.required !== false && blank(values.secrets[f.key]))
      .map((f) => f.key),
    ...(type.config ?? [])
      .filter((f) => f.required !== false && blank(values.settings[f.key]))
      .map((f) => f.key),
  ];
}
