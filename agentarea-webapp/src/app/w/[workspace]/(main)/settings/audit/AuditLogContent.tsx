import { getTranslations } from "next-intl/server";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { getViewerCapabilities } from "@/lib/workspace-context";
import { fetchAuditLogs } from "./actions";
import { auditQuery, isFiltered, type AuditFilters } from "./auditFilters";
import AuditLogClient from "./AuditLogClient";

export default async function AuditLogContent({
  filters,
}: {
  filters: AuditFilters;
}) {
  const { canAdminister } = await getViewerCapabilities();
  if (!canAdminister) {
    return <AdminOnlyState what="auditLog" />;
  }

  // Fixed here, so "Load more" pages through the same window.
  const query = auditQuery(filters, Date.now());
  const { data, error } = await fetchAuditLogs({ ...query, limit: 50 });

  if (!data) {
    const t = await getTranslations("AuditLogPage");
    return (
      <RetryEmptyState
        title={t("loadFailed")}
        description={error}
        iconsType="audit"
      />
    );
  }

  return (
    <AuditLogClient
      initialEvents={data.events}
      initialCursor={data.next_cursor ?? null}
      query={query}
      filtered={isFiltered(filters)}
    />
  );
}
