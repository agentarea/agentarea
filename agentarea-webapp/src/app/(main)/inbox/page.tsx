import type { Metadata } from "next";
import { getInbox, type TaskWithAgent } from "@/lib/api";
import { InboxClient } from "./components/InboxClient";

export const metadata: Metadata = {
  title: "Inbox",
};

type FilterValue = "all" | "pending" | "completed" | "failed";

export default async function InboxPage({
  searchParams,
}: {
  searchParams: Promise<{ filter?: string }>;
}) {
  const { filter } = await searchParams;
  const initialFilter = (
    ["all", "pending", "completed", "failed"].includes(filter ?? "") ? filter : "pending"
  ) as FilterValue;

  let items: TaskWithAgent[] = [];
  let error: string | null = null;

  try {
    const res = await getInbox();
    if (res.error) {
      error = "Failed to load inbox";
    } else {
      items = ((res.data as any)?.items ?? []) as TaskWithAgent[];
    }
  } catch {
    error = "Failed to load inbox";
  }

  return <InboxClient items={items} error={error} initialFilter={initialFilter} />;
}
