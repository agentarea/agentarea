import type { Metadata } from "next";
import { getInbox, type TaskWithAgent } from "@/lib/api";
import { INBOX_PAGE_SIZE } from "@/app/(main)/inbox/components/inboxShared";
import { InboxClient } from "./components/InboxClient";

export const metadata: Metadata = {
  title: "Inbox",
};

export default async function InboxPage() {
  let items: TaskWithAgent[] = [];
  let total = 0;
  let statusCounts: Record<string, number> = {};
  let error: string | null = null;

  try {
    const res = await getInbox({ page: 1, page_size: INBOX_PAGE_SIZE });
    if (res.error) {
      error = "Failed to load inbox";
    } else {
      const data = res.data as any;
      items = (data?.items ?? []) as TaskWithAgent[];
      total = (data?.total ?? items.length) as number;
      statusCounts = (data?.status_counts ?? {}) as Record<string, number>;
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
