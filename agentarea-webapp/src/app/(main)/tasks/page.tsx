import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import SearchInput from "@/components/SearchInput";
import { TasksData } from "./components/TasksData";
import TasksHeaderTabs from "./components/TasksHeaderTabs";
import TasksSkeleton from "./components/TasksSkeleton";

export const metadata: Metadata = {
  title: "Tasks",
};

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
          <SearchInput urlParamName="search" urlPath="/tasks" />
          <TasksHeaderTabs currentTab={tab} />
        </>
      }
    >
      <Suspense
        key={`${searchQuery}-${creator}-${tab}`}
        fallback={<TasksSkeleton viewMode={tab} columns={skeletonColumns} />}
      >
        <TasksData searchQuery={searchQuery} creator={creator} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
