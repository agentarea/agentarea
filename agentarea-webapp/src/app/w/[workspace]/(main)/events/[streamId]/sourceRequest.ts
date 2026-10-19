import type { SecretRef, SourceCreate } from "@/api/client/types.gen";
import { GENERIC_WEBHOOK, type SourceType } from "@/lib/sourceTypes";

export type SourceKind = NonNullable<SourceCreate["kind"]>;

/** The event-template overrides a member may set on a source without a catalog entry of its own. */
export const TEMPLATE_FIELDS = ["kind", "key", "session_key"] as const;
export type TemplateField = (typeof TEMPLATE_FIELDS)[number];

/** What the add-source form holds: a picked secret id per credential, text per setting and template. */
export interface SourceFormValues {
  /** How events arrive, when the type can do both; absent means the type's only way. */
  kind?: SourceKind;
  secrets: Record<string, string>;
  settings: Record<string, string>;
  templates: Partial<Record<TemplateField, string>>;
  /** Raw values of an MCP event's argument fields, by property name. */
  arguments?: Record<string, string | boolean>;
}

/** How events of `type` can arrive: pushed to a webhook, fetched by polling, or either. */
export function sourceKinds(type: SourceType): SourceKind[] {
  if (type.delivery === "both") return ["webhook", "poll"];
  return type.delivery === "poll" ? ["poll"] : ["webhook"];
}

/**
 * Whether the member names the event's kind, key and session on the source:
 * only for the entry that stands for a provider the catalog does not know.
 */
export function takesEventTemplates(type: SourceType): boolean {
  return type.slug === GENERIC_WEBHOOK;
}

/**
 * The create body for a source of `type`: each picked secret by reference,
 * each setting and template trimmed, and anything blank or belonging to
 * another type left out — a blank optional secret is one the platform issues.
 */
export function toSourceRequest(
  type: SourceType,
  values: SourceFormValues
): SourceCreate {
  const credentials: Record<string, SecretRef> = {};
  for (const field of type.credentials) {
    const secretId = values.secrets[field.key]?.trim();
    if (secretId) credentials[field.key] = { secret_id: secretId };
  }
  const config: Record<string, string> = {};
  for (const field of type.config) {
    const value = values.settings[field.key]?.trim();
    if (value) config[field.key] = value;
  }
  const kinds = sourceKinds(type);
  const body: SourceCreate = {
    source_type: type.slug,
    kind: values.kind && kinds.includes(values.kind) ? values.kind : kinds[0],
    credentials,
    config,
  };
  if (takesEventTemplates(type)) {
    const templates: Partial<Record<TemplateField, string>> = {};
    for (const field of TEMPLATE_FIELDS) {
      const value = values.templates[field]?.trim();
      if (value) templates[field] = value;
    }
    if (Object.keys(templates).length > 0) body.event_templates = templates;
  }
  return body;
}

/** Keys of the required fields of `type` that are still blank. */
export function missingSourceFields(
  type: SourceType,
  values: SourceFormValues
): string[] {
  const blank = (value: string | undefined) => !value?.trim();
  return [
    ...type.credentials
      .filter((f) => f.required && !f.issued && blank(values.secrets[f.key]))
      .map((f) => f.key),
    ...type.config
      .filter((f) => f.required && !f.issued && blank(values.settings[f.key]))
      .map((f) => f.key),
  ];
}
