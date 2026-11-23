import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { getDashboard } from "@/lib/api-dashboard";
import TasksSectionTabs from "../components/TasksSectionTabs";
import TasksSkeleton from "../components/TasksSkeleton";
import { UpcomingTasksContent } from "./components/UpcomingTasksContent";
import { expectedRuns } from "./upcoming";

export const metadata: Metadata = {
  title: "Expected tasks",
};

async function UpcomingTasksData() {
  const t = await getTranslations("TasksPage");
  const result = await getDashboard();
  if (!result.data) {
    return <RetryEmptyState title={t("expectedLoadFailed")} />;
  }
  const { runs, frequent } = result.data.schedule;
  return (
    <UpcomingTasksContent rows={expectedRuns(runs, frequent, new Date())} />
  );
}

export default async function UpcomingTasksPage() {
  const t = await getTranslations("TasksPage");
  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: t("title") }] }}
      subheader={<SubheaderToolbar categories={<TasksSectionTabs />} />}
    >
      <Suspense
        fallback={
          <TasksSkeleton
            viewMode="table"
            columns={[
              { header: t("expectedWhen"), barClassName: "h-8 w-24" },
              { header: t("description"), barClassName: "h-4 w-64" },
              { header: t("agent"), barClassName: "h-4 w-28" },
              { header: "", barClassName: "h-6 w-20" },
            ]}
          />
        }
      >
        <UpcomingTasksData />
      </Suspense>
    </ContentBlock>
  );
}
