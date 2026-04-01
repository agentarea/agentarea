import { fetchAuditLogs } from "./actions";
import AuditLogClient from "./AuditLogClient";

export default async function AuditLogPage() {
  const { data, error } = await fetchAuditLogs({ limit: 50 });

  return (
    <AuditLogClient
      initialEvents={data?.events ?? []}
      initialCursor={data?.next_cursor ?? null}
      initialError={error}
    />
  );
}
