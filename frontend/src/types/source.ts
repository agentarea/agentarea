export enum SourceType {
  DATABASE = "database",
  API = "api",
  FILE = "file",
  STREAM = "stream",
}

export enum SourceStatus {
  ACTIVE = "active",
  INACTIVE = "inactive",
  ERROR = "error",
}

export interface Source {
  source_id: string;
  name: string;
  type: SourceType;
  description: string;
  configuration: Record<string, unknown>;
  metadata: Record<string, unknown>;
  owner: string;
  created_at: string;
  updated_at: string;
  status: SourceStatus;
}
