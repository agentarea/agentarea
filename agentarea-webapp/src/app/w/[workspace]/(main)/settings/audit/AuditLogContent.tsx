import { getTranslations } from "next-intl/server";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { getViewerCapabilities } from "@/lib/workspace-context";
import { fetchAuditLogs, listAuditActorOptions } from "./actions";
import AuditLogClient from "./AuditLogClient";

export default async function AuditLogContent() {
  const { canAdminister } = await getViewerCapabilities();
  if (!canAdminister) {
    return <AdminOnlyState what="auditLog" />;
  }

  const [{ data, error }, actorOptions] = await Promise.all([
    fetchAuditLogs({ limit: 50 }),
    listAuditActorOptions(),
  ]);

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
      actorOptions={actorOptions}
    />
  );
}
