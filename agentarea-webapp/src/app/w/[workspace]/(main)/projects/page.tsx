import type { Metadata } from "next";
import { Suspense } from "react";
import { cookies } from "next/headers";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { ViewModeTabs } from "@/components/HeaderTabs";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import CreateProjectButton from "./components/CreateProjectButton";
import ProjectsContent from "./components/ProjectsContent";
import ProjectsSkeleton from "./components/ProjectsSkeleton";

export const metadata: Metadata = {
  title: "Projects",
};

interface ProjectsPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

export default async function ProjectsPage({ searchParams }: ProjectsPageProps) {
  const t = await getTranslations("ProjectsPage");
  const resolvedSearchParams = await searchParams;
  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";

  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_projects")?.value;
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
