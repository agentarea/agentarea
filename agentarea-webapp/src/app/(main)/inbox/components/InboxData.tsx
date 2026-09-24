import { getTranslations } from "next-intl/server";
import { getInbox, type TaskWithAgent } from "@/lib/api";
import { InboxClient } from "./InboxClient";

/**
 * Server data loader for the inbox, isolated behind a <Suspense> boundary in
 * page.tsx so the route can flush its shell immediately and stream the list in
 * once `getInbox()` resolves. Keeping the await out of the page body is what
 * restores time-to-first-byte.
 */
export async function InboxData() {
  const t = await getTranslations("InboxPage");
  let items: TaskWithAgent[] = [];
  let error: string | null = null;

  try {
    const res = await getInbox();
    if (res.error) {
      error = t("loadFailed");
    } else {
      items =
        (res.data as { items?: TaskWithAgent[] } | undefined)?.items ?? [];
    }
  } catch {
    error = t("loadFailed");
  }

  return <InboxClient items={items} error={error} />;
}
