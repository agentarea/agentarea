"use server";

import { listAuditLogs } from "@/lib/api";

export interface AuditChange {
  field: string;
  before?: unknown;
  after?: unknown;
}

export interface AuditEvent {
  id: string;
  action: string;
  actor_id: string;
  resource_type: string;
  resource_id?: string | null;
  source_ip?: string | null;
  created_at: string;
  changes?: AuditChange[];
}

export interface AuditLogResponse {
  events: AuditEvent[];
  next_cursor: string | null;
}

export async function fetchAuditLogs(params?: {
  action?: string;
  resource_type?: string;
  actor_id?: string;
  resource_id?: string;
  since?: string;
  until?: string;
  cursor?: string;
  limit?: number;
}): Promise<{ data: AuditLogResponse | null; error: string | null }> {
  const { data, error } = await listAuditLogs(params);

  if (error) {
    return { data: null, error: "Failed to fetch audit logs" };
  }

  return { data: data as unknown as AuditLogResponse, error: null };
}
