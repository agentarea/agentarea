"use server";

import { listAuditLogs } from "@/lib/api";
import type { components } from "@/api/schema";

export type AuditEvent = components["schemas"]["AuditEventResponse"];
export type AuditLogResponse = components["schemas"]["AuditLogListResponse"];

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

  return { data: data as AuditLogResponse, error: null };
}
