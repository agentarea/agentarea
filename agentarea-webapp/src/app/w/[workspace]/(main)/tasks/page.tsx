import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import SearchInput from "@/components/SearchInput";
import { parsePageParam } from "@/lib/offsetPage";
import { statusesForFilter } from "@/lib/taskStatusFilter";
import { TasksData } from "./components/TasksData";
import TasksHeaderTabs from "./components/TasksHeaderTabs";
import TasksSkeleton from "./components/TasksSkeleton";
import TasksStatusFilter from "./components/TasksStatusFilter";

export const metadata: Metadata = {
  title: "Tasks",
};

const RESET_ON_SEARCH = ["page"];

interface TasksPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function TasksPage({ searchParams }: TasksPageProps) {
  const t = await getTranslations("TasksPage");
  const resolvedSearchParams = await searchParams;
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";
  // Set by the "Started by" cell, which links to that person's tasks.
  const creator =
    typeof resolvedSearchParams.creator === "string"
      ? resolvedSearchParams.creator
      : "";
  const rawStatus = resolvedSearchParams.status;
  const statuses =
    rawStatus === undefined
      ? []
      : typeof rawStatus === "string"
        ? statusesForFilter(rawStatus)
        : null;
  if (statuses === null) notFound();
  const page = parsePageParam(resolvedSearchParams.page);
  if (page === null) notFound();

  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_tasks")?.value;
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "table";

  const skeletonColumns = [
    { header: t("description"), barClassName: "h-4 w-48" },
    { header: t("agent"), barClassName: "h-4 w-28" },
    { header: t("statusLabel"), barClassName: "h-5 w-20 rounded-full" },
    { header: t("source"), barClassName: "h-4 w-24" },
    { header: t("cost"), barClassName: "h-4 w-12" },
    { header: t("created"), barClassName: "h-8 w-24" },
  ];

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
      }}
      subheader={
        <>
          <SearchInput
            urlParamName="search"
            urlPath="/tasks"
            resetParamNames={RESET_ON_SEARCH}
          />
          <TasksStatusFilter />
          <TasksHeaderTabs currentTab={tab} />
        </>
      }
    >
      <Suspense
        key={`${searchQuery}-${creator}-${statuses.join(",")}-${page}-${tab}`}
        fallback={<TasksSkeleton viewMode={tab} columns={skeletonColumns} />}
      >
        <TasksData
          searchQuery={searchQuery}
          creator={creator}
          statuses={statuses}
          page={page}
          searchParams={resolvedSearchParams}
          viewMode={tab}
        />
      </Suspense>
    </ContentBlock>
  );
}
