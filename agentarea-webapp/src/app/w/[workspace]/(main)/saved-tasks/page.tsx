import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { ViewModeTabs } from "@/components/HeaderTabs";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import CreateSavedTaskButton from "./components/CreateSavedTaskButton";
import SavedTasksContent from "./components/SavedTasksContent";
import SavedTasksSkeleton from "./components/SavedTasksSkeleton";

export const metadata: Metadata = {
  title: "Saved tasks",
};

interface SavedTasksPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function SavedTasksPage({
  searchParams,
}: SavedTasksPageProps) {
  const t = await getTranslations("SavedTasksPage");
  const resolvedSearchParams = await searchParams;
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";

  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_saved-tasks")?.value;
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "table";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: <CreateSavedTaskButton />,
      }}
      subheader={
        <SubheaderToolbar
          search={
            <SearchInput
              urlParamName="search"
              urlPath="/saved-tasks"
              placeholder={t("searchPlaceholder")}
            />
          }
          controls={<ViewModeTabs currentTab={tab} defaultTab="table" />}
        />
      }
    >
      <Suspense
        key={`${searchQuery}-${tab}`}
        fallback={<SavedTasksSkeleton viewMode={tab} />}
      >
        <SavedTasksContent searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
