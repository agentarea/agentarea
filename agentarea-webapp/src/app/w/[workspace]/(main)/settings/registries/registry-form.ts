// The registry form's values and how they become the API's request bodies.
// No React here: the dialog and the server actions share it.

import type {
  RegistryResponse,
  WorkspaceRegistryCreate,
  WorkspaceRegistryUpdate,
} from "@/api/client/types.gen";
import { zWorkspaceRegistryCreate } from "@/api/client/zod.gen";

export type RegistrySourceType = WorkspaceRegistryCreate["source_type"];
export type WorkspaceRegistryType = NonNullable<
  WorkspaceRegistryCreate["registry_type"]
>;
export type WorkspaceRegistryTrust = NonNullable<
  WorkspaceRegistryCreate["trust"]
>;

// The choices the API accepts, read from its schema rather than listed here.
export const SOURCE_TYPES: readonly RegistrySourceType[] =
  zWorkspaceRegistryCreate.shape.source_type.options;
export const REGISTRY_TYPES: readonly WorkspaceRegistryType[] =
  zWorkspaceRegistryCreate.shape.registry_type.removeDefault().unwrap().options;
export const WORKSPACE_TRUST_LEVELS: readonly WorkspaceRegistryTrust[] =
  zWorkspaceRegistryCreate.shape.trust.removeDefault().unwrap().options;

/** What the form edits. Optional text is "" until filled; "" secret is none. */
export type RegistryFormValues = {
  name: string;
  description: string;
  source_type: RegistrySourceType;
  source_url: string;
  source_ref: string;
  source_path: string;
  registry_type: WorkspaceRegistryType;
  trust: WorkspaceRegistryTrust;
  credentials_secret_id: string;
  is_active: boolean;
};

export function emptyRegistryForm(): RegistryFormValues {
  return {
    name: "",
    description: "",
    source_type: "github",
    source_url: "",
    source_ref: "",
    source_path: "",
    registry_type: "skills",
    trust: "private",
    credentials_secret_id: "",
    is_active: true,
  };
}

function asWorkspaceTrust(trust: RegistryResponse["trust"]) {
  return WORKSPACE_TRUST_LEVELS.find((level) => level === trust) ?? "private";
}

export function registryToForm(registry: RegistryResponse): RegistryFormValues {
  return {
    name: registry.name,
    description: registry.description ?? "",
    source_type: registry.source_type === "url" ? "url" : "github",
    source_url: registry.source_url,
    source_ref: registry.source_ref ?? "",
    source_path: registry.source_path ?? "",
    registry_type: registry.registry_type === "agents" ? "agents" : "skills",
    trust: asWorkspaceTrust(registry.trust),
    credentials_secret_id: registry.credentials_secret_id ?? "",
    is_active: registry.is_active,
  };
}

const optional = (value: string) => value.trim() || null;

/** Ref and path only mean something for a GitHub repository. */
function gitLocation(form: RegistryFormValues) {
  return form.source_type === "github"
    ? {
        source_ref: optional(form.source_ref),
        source_path: optional(form.source_path),
      }
    : { source_ref: null, source_path: null };
}

export function toRegistryCreate(
  form: RegistryFormValues
): WorkspaceRegistryCreate {
  return {
    name: form.name.trim(),
    description: optional(form.description),
    source_type: form.source_type,
    source_url: form.source_url.trim(),
    ...gitLocation(form),
    registry_type: form.registry_type,
    trust: form.trust,
    credentials_secret_id: optional(form.credentials_secret_id),
  };
}

/**
 * Every editable field, so clearing one (the secret, the ref) clears it on the
 * server: an explicit null there means "none", an absent field "unchanged".
 * The source kind and the registry type are fixed once the registry exists.
 */
export function toRegistryUpdate(
  form: RegistryFormValues
): WorkspaceRegistryUpdate {
  return {
    name: form.name.trim(),
    description: optional(form.description),
    source_url: form.source_url.trim(),
    ...gitLocation(form),
    trust: form.trust,
    credentials_secret_id: optional(form.credentials_secret_id),
    is_active: form.is_active,
  };
}

/** Where a registry reads from, in one line: `owner/repo@ref:path` or the URL. */
export function describeRegistrySource(
  registry: Pick<
    RegistryResponse,
    "source_type" | "source_url" | "source_ref" | "source_path"
  >
): string {
  if (registry.source_type !== "github") return registry.source_url;
  const ref = registry.source_ref ? `@${registry.source_ref}` : "";
  const path = registry.source_path ? `:${registry.source_path}` : "";
  return `${registry.source_url}${ref}${path}`;
}
