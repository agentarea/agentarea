import type { AuditEventResponse } from "@/api/client/types.gen";
import { auditChangeLines } from "./auditChanges";

/** The columns of an exported audit log, in order. */
export const AUDIT_CSV_COLUMNS = [
  "created_at",
  "action",
  "actor_type",
  "actor_id",
  "resource_type",
  "resource_id",
  "source_ip",
  "details",
  "changes",
] as const;

/**
 * A cell as CSV text. Quoted when it holds a separator, quote or newline; a
 * cell a spreadsheet would run as a formula (`=`, `+`, `-`, `@`, tab, CR) is
 * prefixed with `'` so opening the export never executes what an actor typed.
 */
function csvCell(value: string): string {
  const safe = /^[=+\-@\t\r]/.test(value) ? `'${value}` : value;
  return /[",\n\r]/.test(safe) ? `"${safe.replaceAll('"', '""')}"` : safe;
}

export function auditEventsToCsv(
  events: readonly AuditEventResponse[]
): string {
  const rows = events.map((event) => {
    const changes = auditChangeLines(event.changes)
      .map((line) => `${line.field}: ${line.before} -> ${line.after}`)
      .join("; ");
    return [
      event.created_at,
      event.action,
      event.actor_type,
      event.actor_id,
      event.resource_type,
      event.resource_id ?? "",
      event.source_ip ?? "",
      Object.keys(event.event_metadata ?? {}).length
        ? JSON.stringify(event.event_metadata)
        : "",
      changes,
    ]
      .map(csvCell)
      .join(",");
  });
  return [AUDIT_CSV_COLUMNS.join(","), ...rows].join("\r\n") + "\r\n";
}
