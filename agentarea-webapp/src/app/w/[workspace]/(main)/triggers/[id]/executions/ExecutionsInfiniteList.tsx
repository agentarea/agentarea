"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import LoadMoreSentinel from "@/components/LoadMoreSentinel";
import { fetchExecutionsPageAction } from "../actions";
import type { ExecutionsPage } from "./executionsPage";
import ExecutionsTable from "./ExecutionsTable";

/** A trigger's runs, the next page loading as the table's end scrolls into view. */
export default function ExecutionsInfiniteList({
  triggerId,
  firstPage,
  currency,
}: {
  triggerId: string;
  firstPage: ExecutionsPage;
  /** The workspace's billing currency, loaded by the page as the overview does. */
  currency: string | null;
}) {
  const t = useTranslations("TriggersPage.detail");
  const [executions, setExecutions] = useState(firstPage.executions);
  const [principalNames, setPrincipalNames] = useState(
    firstPage.principalNames
  );
  const [nextPage, setNextPage] = useState(firstPage.hasNext ? 2 : null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const loadMore = () => {
    if (nextPage === null || isPending) return;
    startTransition(async () => {
      const page = await fetchExecutionsPageAction(triggerId, nextPage);
      if (!page) {
        setLoadMoreError(t("executionsLoadFailed"));
        return;
      }
      setLoadMoreError(null);
      // Pages are offsets into a history that grows at the top, so a run
      // since the last page shifts one already shown into this one.
      setExecutions((prev) => {
        const shown = new Set(prev.map((execution) => execution.id));
        return [
          ...prev,
          ...page.executions.filter((execution) => !shown.has(execution.id)),
        ];
      });
      setPrincipalNames((prev) => ({ ...prev, ...page.principalNames }));
      setNextPage(page.hasNext ? nextPage + 1 : null);
    });
  };

  return (
    <>
      <ExecutionsTable
        executions={executions}
        principalNames={principalNames}
        currency={currency}
      />
      <LoadMoreSentinel
        hasMore={nextPage !== null}
        pending={isPending}
        error={loadMoreError}
        onLoadMore={loadMore}
      />
    </>
  );
}
