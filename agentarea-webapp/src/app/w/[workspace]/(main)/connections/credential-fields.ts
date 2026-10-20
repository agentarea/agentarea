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

// The API rejects these in an instance update and restores them itself
// (INSTANCE_TRANSPORT_FIELDS in agentarea_mcp/schemas/dto.py).
const TRANSPORT_FIELDS = new Set([
  "type",
  "endpoint_url",
  "image",
  "command",
  "args",
  "port",
  "package",
  "source",
]);

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

// How the API returns a value it keeps in the secret store.
const MASKED_VALUE = "******";

export interface StoredHeader {
  name: string;
  secret: boolean;
  value?: string;
}

/** A remote connection's headers as the API returns them, secrets masked. */
export function storedHeaders(instanceJsonSpec: Record<string, unknown>): StoredHeader[] {
  return Object.entries(stringRecord(instanceJsonSpec.headers)).map(([name, value]) =>
    value === MASKED_VALUE ? { name, secret: true } : { name, secret: false, value }
  );
}

/**
 * The instance update that makes a remote connection's headers exactly `rows`.
 * A blank value keeps a stored secret; a header left out is removed, from
 * `env_vars` too, since every secret a remote connection holds is sent as a
 * header.
 */
export function headersUpdateSpec(
  instanceJsonSpec: Record<string, unknown>,
  rows: { name: string; value: string }[]
): Record<string, unknown> {
  const stored = stringRecord(instanceJsonSpec.headers);
  const headers: Record<string, string> = {};
  for (const row of rows) {
    const name = row.name.trim();
    const value = row.value.trim();
    if (!name) continue;
    if (value) headers[name] = value;
    else if (stored[name] === MASKED_VALUE) headers[name] = MASKED_VALUE;
  }
  const removed = new Set(Object.keys(stored).filter((name) => !(name in headers)));

  const spec: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(instanceJsonSpec)) {
    if (!TRANSPORT_FIELDS.has(key)) spec[key] = value;
  }
  spec.headers = headers;
  if (Array.isArray(instanceJsonSpec.env_vars)) {
    spec.env_vars = stringList(instanceJsonSpec.env_vars).filter((name) => !removed.has(name));
  }
  if (isRecord(instanceJsonSpec.environment)) {
    spec.environment = Object.fromEntries(
      Object.entries(instanceJsonSpec.environment).filter(([name]) => !removed.has(name))
    );
  }
  return spec;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
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
