import { getTranslations } from "next-intl/server";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { getViewerCapabilities } from "@/lib/workspace-context";
import { fetchAuditLogs } from "../../../settings/audit/actions";
import AuditLogClient from "../../../settings/audit/AuditLogClient";

interface Props {
  params: Promise<{ id: string }>;
}

/**
 * The connection's change history: the workspace audit log, scoped to this
 * one MCP instance and drawn by the same table.
 */
export default async function ConnectionActivityPage({ params }: Props) {
  const { id } = await params;
  const { canAdminister } = await getViewerCapabilities();

  if (!canAdminister) {
    return <AdminOnlyState what="auditLog" />;
  }

  // Fixed here, so "Load more" pages through the same scope.
  const query = { resource_type: "mcp_instance", resource_id: id };
  const { data, error } = await fetchAuditLogs({ ...query, limit: 50 });

  return (
    <div className="h-full overflow-y-auto px-4 py-5">
      {data ? (
        <AuditLogClient
          initialEvents={data.events}
          initialCursor={data.next_cursor ?? null}
          query={query}
          filtered={false}
          resourceScoped
        />
      ) : (
        <RetryEmptyState
          title={(await getTranslations("AuditLogPage"))("loadFailed")}
          description={error}
          iconsType="audit"
        />
      )}
    </div>
  );
}
