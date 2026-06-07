// TODO: replace with generated components['schemas'] after running npm run generate:schema
// (requires the backend API running on :8000 — run `npm run generate:schema` post-deploy)

export type SetupFieldType = "secret" | "string" | "number" | "boolean" | "select";

export interface SetupField {
  key: string;
  label: string;
  type: SetupFieldType;
  required: boolean;
  help?: string | null;
  default?: string | number | boolean | null;
  options?: string[] | null;
  min?: number | null;
  max?: number | null;
}

export interface PackageMcp {
  key: string;
  name: string;
  [key: string]: unknown;
}

export interface PackageSkill {
  key: string;
  name: string;
  [key: string]: unknown;
}

export interface PackageAgent {
  key: string;
  name: string;
  [key: string]: unknown;
}

export interface PackageAutomation {
  key: string;
  name: string;
  [key: string]: unknown;
}

export interface Bundle {
  schema_version: string;
  name: string;
  display_name?: string | null;
  description: string;
  setup: SetupField[];
  mcps: PackageMcp[];
  skills: PackageSkill[];
  agents: PackageAgent[];
  automations: PackageAutomation[];
}

export type EntityKind = "mcp" | "skill" | "agent" | "automation";
export type EntityStatus = "will_create" | "already_exists" | "unsupported";
export type IssueSeverity = "block" | "warn";

export interface PreviewEntity {
  kind: EntityKind;
  key: string;
  name: string;
  status: EntityStatus;
  detail?: string | null;
}

export interface PreviewIssue {
  severity: IssueSeverity;
  message: string;
  entity_key?: string | null;
}

export interface ImportPreview {
  bundle: Bundle;
  setup: SetupField[];
  entities: PreviewEntity[];
  issues: PreviewIssue[];
  installable: boolean;
}

export type InstallAction = "created" | "reused" | "skipped";

export interface InstalledEntity {
  kind: EntityKind;
  key: string;
  name: string;
  action: InstallAction;
  id?: string | null;
  detail?: string | null;
}

export interface InstallResult {
  bundle_name: string;
  installed_bundle_id?: string | null;
  entities: InstalledEntity[];
}
