"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import type { TriggerCatalogEntry } from "@/app/w/[workspace]/(main)/triggers/components/triggerDisplay";
import LoadMoreSentinel from "@/components/LoadMoreSentinel";
import { fetchTasksPage, type TasksPageResult, type TasksQuery } from "../actions";
import TasksList from "./TasksList";

interface TasksInfiniteListProps {
  firstPage: TasksPageResult;
  /** The query the first page loaded with, for the pages after it. */
  query: TasksQuery;
  viewMode: string;
  catalog: TriggerCatalogEntry[];
}

/** The task list, the next page loading as its end scrolls into view. */
export default function TasksInfiniteList({
  firstPage,
  query,
  viewMode,
  catalog,
}: TasksInfiniteListProps) {
  const t = useTranslations("TasksPage");
  const [tasks, setTasks] = useState(firstPage.tasks);
  const [principalNames, setPrincipalNames] = useState(
    firstPage.principalNames
  );
  const [nextPage, setNextPage] = useState(firstPage.hasNext ? 2 : null);
  const [loadMoreError, setLoadMoreError] = useState<string | null>(null);
  const [isPending, startTransition] = useTransition();

  const loadMore = () => {
    if (nextPage === null || isPending) return;
    startTransition(async () => {
      const page = await fetchTasksPage(query, nextPage);
      if (!page) {
        setLoadMoreError(t("error.loadFailedDescription"));
        return;
      }
      setLoadMoreError(null);
      // Pages are offsets into a list that grows at the top, so a task started
      // since the last page shifts one already shown into this one.
      setTasks((prev) => {
        const shown = new Set(prev.map((task) => task.id));
        return [...prev, ...page.tasks.filter((task) => !shown.has(task.id))];
      });
      setPrincipalNames((prev) => ({ ...prev, ...page.principalNames }));
      setNextPage(page.hasNext ? nextPage + 1 : null);
    });
  };

  return (
    <>
      <TasksList
        initialTasks={tasks}
        viewMode={viewMode}
        catalog={catalog}
        principalNames={principalNames}
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
