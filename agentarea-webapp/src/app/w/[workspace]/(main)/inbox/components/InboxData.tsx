import { getTranslations } from "next-intl/server";
import { client as serverClient } from "@/api/client/client.gen";
import { listApprovalDecisionsV1InboxDecisionsGet } from "@/api/client/sdk.gen";
import { resolvePrincipalNamesAction } from "@/components/Approvals/actions";
import { getInbox, type TaskWithAgent } from "@/lib/api";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { InboxClient } from "./InboxClient";
import type { InboxDecision } from "./inboxShared";

const DECISIONS_PAGE_SIZE = 100;

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
  let decisions: InboxDecision[] = [];
  let decisionsTotal = 0;
  let decisionsError: string | null = null;

  try {
    const res = await getInbox();
    if (res.error) {
      console.error("Failed to load inbox", res.error);
      error = apiErrorMessage(res, t("loadFailed"));
    } else {
      items =
        (res.data as { items?: TaskWithAgent[] } | undefined)?.items ?? [];
    }
  } catch (err) {
    console.error("Failed to load inbox", err);
    error = `${t("loadFailed")}: ${formatApiError(err)}`;
  }

  try {
    const res = await listApprovalDecisionsV1InboxDecisionsGet({
      client: serverClient,
      query: { page_size: DECISIONS_PAGE_SIZE },
    });
    if (res.error || !res.data) {
      console.error("Failed to load approval decisions", res.error);
      decisionsError = apiErrorMessage(res, t("decisions.loadFailed"));
    } else {
      decisionsTotal = res.data.total;
      const deciderIds = [
        ...new Set(
          res.data.items
            .map((decision) => decision.decided_by)
            .filter((id): id is string => Boolean(id))
        ),
      ];
      let names: Record<string, string> = {};
      try {
        names = (await resolvePrincipalNamesAction(deciderIds)).data;
      } catch (err) {
        console.error("Failed to resolve approval deciders", err);
      }
      decisions = res.data.items.map((decision) => ({
        ...decision,
        decided_by_name: decision.decided_by
          ? (names[decision.decided_by] ?? null)
          : null,
      }));
    }
  } catch (err) {
    console.error("Failed to load approval decisions", err);
    decisionsError = `${t("decisions.loadFailed")}: ${formatApiError(err)}`;
  }

  return (
    <InboxClient
      items={items}
      error={error}
      decisions={decisions}
      decisionsTotal={decisionsTotal}
      decisionsError={decisionsError}
    />
  );
}
