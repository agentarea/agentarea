import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import TasksSectionTabs from "../components/TasksSectionTabs";
import TasksSkeleton from "../components/TasksSkeleton";
import SavedTasksContent from "./components/SavedTasksContent";

export const metadata: Metadata = {
  title: "Saved tasks",
};

export default async function SavedTasksPage() {
  const t = await getTranslations("TasksPage");
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
      }}
      subheader={<SubheaderToolbar categories={<TasksSectionTabs />} />}
    >
      <Suspense
        fallback={
          <TasksSkeleton
            viewMode="table"
            columns={[
              { header: t("savedName"), barClassName: "h-4 w-64" },
              { header: t("agent"), barClassName: "h-4 w-28" },
              { header: "", barClassName: "h-6 w-20" },
            ]}
          />
        }
      >
        <SavedTasksContent />
      </Suspense>
    </ContentBlock>
  );
}
