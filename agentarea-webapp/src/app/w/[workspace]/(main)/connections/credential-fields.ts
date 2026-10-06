/**
 * The credential inputs a connection declares and which of them still lack a
 * value. Shared by the create form, the connection page and the connect link.
 */

import type { McpTransport } from "@/api/client/types.gen";

export interface CredentialFieldSpec {
  name: string;
  description?: string;
  isRequired?: boolean;
  /** Older spelling of `isRequired`, read only when that is absent. */
  required?: boolean;
  isSecret?: boolean;
  default?: string;
  placeholder?: string;
  choices?: string[];
}

type ServerSpecLike = {
  env_schema?: unknown;
  json_spec?: Record<string, unknown> | null;
};

// The API rejects these in an instance update and restores them itself.
const TRANSPORT_FIELDS = new Set(["type", "endpoint_url", "image", "command", "args"]);

export function parseFieldSpecs(value: unknown): CredentialFieldSpec[] {
  if (!Array.isArray(value)) return [];

  const fields: CredentialFieldSpec[] = [];
  for (const candidate of value) {
    const entry: unknown = candidate;
    if (
      typeof entry !== "object" ||
      entry === null ||
      Array.isArray(entry) ||
      !("name" in entry) ||
      typeof entry.name !== "string"
    ) {
      continue;
    }

    const field: CredentialFieldSpec = { name: entry.name };
    if ("description" in entry && typeof entry.description === "string") {
      field.description = entry.description;
    }
    if ("isRequired" in entry && typeof entry.isRequired === "boolean") {
      field.isRequired = entry.isRequired;
    }
    if ("required" in entry && typeof entry.required === "boolean") {
      field.required = entry.required;
    }
    if ("isSecret" in entry && typeof entry.isSecret === "boolean") { // pragma: allowlist secret
      field.isSecret = entry.isSecret;
    }
    if ("default" in entry && typeof entry.default === "string") {
      field.default = entry.default;
    }
    if ("placeholder" in entry && typeof entry.placeholder === "string") {
      field.placeholder = entry.placeholder;
    }
    if ("choices" in entry && Array.isArray(entry.choices)) {
      field.choices = entry.choices.filter(
        (choice: unknown): choice is string => typeof choice === "string"
      );
    }
    fields.push(field);
  }
  return fields;
}

/** A remote server's headers: its first remote's, else its env schema. */
export function remoteHeaderFields(
  server: ServerSpecLike | null | undefined
): CredentialFieldSpec[] {
  if (!server) return [];
  const remotes = server.json_spec?.remotes;
  if (Array.isArray(remotes)) {
    const remote: unknown = remotes[0];
    if (
      typeof remote === "object" &&
      remote !== null &&
      !Array.isArray(remote) &&
      "headers" in remote &&
      Array.isArray(remote.headers)
    ) {
      return parseFieldSpecs(remote.headers);
    }
  }
  return parseFieldSpecs(server.env_schema);
}

/** The fields a connection of this transport is configured through. */
export function declaredCredentialFields(
  server: ServerSpecLike | null | undefined,
  transport: McpTransport
): CredentialFieldSpec[] {
  if (transport === "url") return remoteHeaderFields(server);
  return parseFieldSpecs(server?.env_schema);
}

/**
 * Secret fields the connection cannot work without. Same rule as the API's
 * env_schema normalizer: `isRequired`, else `required`, else optional.
 */
export function requiredSecretFields(
  fields: CredentialFieldSpec[]
): CredentialFieldSpec[] {
  return fields.filter(
    (field) => field.isSecret === true && (field.isRequired ?? field.required) === true
  );
}

/**
 * Required secret fields the connection holds no value for. A stored secret is
 * named in `env_vars` (its value never comes back); a plain value sits in
 * `headers` / `environment`.
 */
export function missingSecretFields(
  fields: CredentialFieldSpec[],
  instanceJsonSpec: Record<string, unknown>
): CredentialFieldSpec[] {
  const stored = new Set(stringList(instanceJsonSpec.env_vars));
  const values = {
    ...stringRecord(instanceJsonSpec.environment),
    ...stringRecord(instanceJsonSpec.headers),
  };
  return requiredSecretFields(fields).filter(
    (field) => !stored.has(field.name) && !values[field.name]?.trim()
  );
}

/**
 * The instance update that adds `values` to a connection: the whole current
 * spec (an update replaces it), with the values merged into the headers of a
 * remote connection or the environment of a container.
 */
export function credentialUpdateSpec(
  instanceJsonSpec: Record<string, unknown>,
  transport: McpTransport,
  values: Record<string, string>
): Record<string, unknown> {
  const target = transport === "url" ? "headers" : "environment";
  const entered: Record<string, string> = {};
  for (const [name, value] of Object.entries(values)) {
    const trimmed = value.trim();
    if (trimmed) entered[name] = trimmed;
  }
  const spec: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(instanceJsonSpec)) {
    if (!TRANSPORT_FIELDS.has(key)) spec[key] = value;
  }
  spec[target] = { ...stringRecord(instanceJsonSpec[target]), ...entered };
  return spec;
}

function stringList(value: unknown): string[] {
  return Array.isArray(value)
    ? value.filter((item): item is string => typeof item === "string")
    : [];
}

function stringRecord(value: unknown): Record<string, string> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) {
    return {};
  }
  const record: Record<string, string> = {};
  for (const [key, item] of Object.entries(value)) {
    if (typeof item === "string") record[key] = item;
  }
  return record;
}
