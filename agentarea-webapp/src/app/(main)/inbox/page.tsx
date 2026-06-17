import type { Metadata } from "next";
import { getInbox, type TaskWithAgent } from "@/lib/api";
import { InboxClient } from "./components/InboxClient";

export const metadata: Metadata = {
  title: "Inbox",
};

export default async function InboxPage() {
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

  return <InboxClient items={items} error={error} />;
}
