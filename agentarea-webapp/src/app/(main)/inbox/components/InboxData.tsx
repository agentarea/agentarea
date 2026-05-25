import { getInbox, type TaskWithAgent } from "@/lib/api";
import { InboxTabs } from "./InboxTabs";
import { InboxList } from "./InboxList";

type FilterValue = "all" | "pending" | "completed" | "failed";

interface InboxDataProps {
  filter: FilterValue;
}

export async function InboxData({ filter }: InboxDataProps) {
  let allItems: TaskWithAgent[] = [];
  let pendingItems: TaskWithAgent[] = [];
  let completedItems: TaskWithAgent[] = [];
  let failedItems: TaskWithAgent[] = [];
  let error: string | null = null;

  try {
    const [allRes, pendingRes, completedRes, failedRes] = await Promise.all([
      getInbox(),
      getInbox({ status: "pending" }),
      getInbox({ status: "completed" }),
      getInbox({ status: "failed" }),
    ]);

    if (allRes.error || pendingRes.error || completedRes.error || failedRes.error) {
      error = "Failed to load inbox";
    } else {
      allItems = (allRes.data as any)?.items || [];
      pendingItems = (pendingRes.data as any)?.items || [];
      completedItems = (completedRes.data as any)?.items || [];
      failedItems = (failedRes.data as any)?.items || [];
    }
  } catch {
    error = "Failed to load inbox";
  }

  if (error) {
    return <div className="py-6 text-center text-red-500">{error}</div>;
  }

  const counts = {
    all: allItems.length,
    pending: pendingItems.length,
    completed: completedItems.length,
    failed: failedItems.length,
  };

  const displayItems: Record<FilterValue, TaskWithAgent[]> = {
    all: allItems,
    pending: pendingItems,
    completed: completedItems,
    failed: failedItems,
  };

  return (
    <>
      <InboxTabs active={filter} counts={counts} />
      <InboxList items={displayItems[filter]} filter={filter} />
    </>
  );
}
