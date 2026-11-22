import { getTranslations } from "next-intl/server";
import { AdminOnlyState } from "@/components/AdminOnlyState";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { getViewerCapabilities } from "@/lib/workspace-context";
import { fetchAuditLogs } from "../../../settings/audit/actions";
import AuditLogClient from "../../../settings/audit/AuditLogClient";
import { getMemberCached } from "../memberDetail";

interface Props {
  params: Promise<{ userId: string }>;
}

/** What this member did: the workspace audit log, scoped to them as actor. */
export default async function MemberActivityPage({ params }: Props) {
  const { userId } = await params;
  const [{ member }, { canAdminister }] = await Promise.all([
    getMemberCached(userId),
    getViewerCapabilities(),
  ]);

  if (!canAdminister) {
    return <AdminOnlyState what="auditLog" />;
  }

  // Fixed here, so "Load more" pages through the same scope.
  const query = { actor_id: member.user_id };
  const { data, error } = await fetchAuditLogs({ ...query, limit: 50 });

  return (
    <div className="h-full overflow-y-auto px-4 py-5">
      {data ? (
        <AuditLogClient
          initialEvents={data.events}
          initialCursor={data.next_cursor ?? null}
          query={query}
          filtered={false}
          actorScoped
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
