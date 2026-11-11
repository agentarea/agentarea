import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { ViewModeTabs } from "@/components/HeaderTabs";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { readUiPrefs } from "@/lib/ui-prefs-server";
import CreateProjectButton from "./components/CreateProjectButton";
import ProjectsContent from "./components/ProjectsContent";
import ProjectsSkeleton from "./components/ProjectsSkeleton";

export const metadata: Metadata = {
  title: "Projects",
};

interface ProjectsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function ProjectsPage({
  searchParams,
}: ProjectsPageProps) {
  const t = await getTranslations("ProjectsPage");
  const resolvedSearchParams = await searchParams;
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";

  // Read tab from URL, else the remembered view
  const uiPrefs = await readUiPrefs();
  const cookieTab = uiPrefs.views["tab_projects"];
  const tab =
    typeof resolvedSearchParams.tab === "string"
      ? resolvedSearchParams.tab
      : cookieTab || "grid";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: <CreateProjectButton />,
      }}
      subheader={
        <SubheaderToolbar
          search={
            <SearchInput
              urlParamName="search"
              urlPath="/projects"
              placeholder={t("searchPlaceholder")}
            />
          }
          controls={<ViewModeTabs currentTab={tab} />}
        />
      }
    >
      <Suspense
        key={`${searchQuery}-${tab}`}
        fallback={<ProjectsSkeleton viewMode={tab} />}
      >
        <ProjectsContent searchQuery={searchQuery} viewMode={tab} />
      </Suspense>
    </ContentBlock>
  );
}
