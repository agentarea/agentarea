import { getInbox, type TaskWithAgent } from "@/lib/api";
import { INBOX_PAGE_SIZE } from "@/app/(main)/inbox/components/inboxShared";
import { InboxClient } from "./InboxClient";

/**
 * Server data loader for the inbox, isolated behind a <Suspense> boundary in
 * page.tsx so the route can flush its shell immediately and stream the list in
 * once `getInbox()` resolves. Keeping the await out of the page body is what
 * restores time-to-first-byte.
 */
export async function InboxData() {
  let items: TaskWithAgent[] = [];
  let total = 0;
  let statusCounts: Record<string, number> = {};
  let error: string | null = null;

  try {
    const res = await getInbox({ page: 1, page_size: INBOX_PAGE_SIZE });
    if (res.error) {
      error = "Failed to load inbox";
    } else {
      const data = res.data as
        | {
            items?: TaskWithAgent[];
            total?: number;
            status_counts?: Record<string, number>;
          }
        | undefined;
      items = data?.items ?? [];
      total = data?.total ?? items.length;
      statusCounts = data?.status_counts ?? {};
    }
  } catch {
    error = "Failed to load inbox";
  }

  return (
    <InboxClient
      initialItems={items}
      initialTotal={total}
      initialStatusCounts={statusCounts}
      pageSize={INBOX_PAGE_SIZE}
      error={error}
    />
  );
}
