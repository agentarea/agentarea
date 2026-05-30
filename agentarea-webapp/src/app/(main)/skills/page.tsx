import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import SearchInput from "@/components/SearchInput";
import CreateSkillButton from "./components/CreateSkillButton";
import SkillsContent from "./components/SkillsContent";
import SkillsFilters from "./components/SkillsFilters";
import SkillsHeaderTabs from "./components/SkillsHeaderTabs";

export const metadata = {
  title: "Skills",
};

export default async function SkillsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("SkillsPage");
  const resolvedSearchParams = await searchParams;

  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_skills")?.value;
  const viewMode =
    typeof resolvedSearchParams.tab === "string"
      ? (resolvedSearchParams.tab as "grid" | "table")
      : (cookieTab as "grid" | "table") || "grid";

  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";
  const rawPage =
    typeof resolvedSearchParams.page === "string"
      ? Number.parseInt(resolvedSearchParams.page, 10)
      : 1;
  const page = Number.isFinite(rawPage) && rawPage > 0 ? rawPage : 1;
  const sourceType =
    typeof resolvedSearchParams.source_type === "string"
      ? resolvedSearchParams.source_type
      : "";
  const filesFilter =
    typeof resolvedSearchParams.files === "string"
      ? resolvedSearchParams.files
      : "all";
  const hasFiles =
    filesFilter === "with_files"
      ? true
      : filesFilter === "without_files"
        ? false
        : undefined;
  const networkScope =
    typeof resolvedSearchParams.network_scope === "string"
      ? resolvedSearchParams.network_scope
      : "";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
        controls: <CreateSkillButton />,
      }}
      subheader={
        <>
          <SearchInput
            urlParamName="search"
            urlPath="/skills"
            resetParamNames={["page"]}
          />
          <SkillsFilters
            sourceType={sourceType}
            filesFilter={filesFilter}
            networkScope={networkScope}
          />
          <SkillsHeaderTabs currentTab={viewMode} />
        </>
      }
    >
      <Suspense
        key={`${viewMode}-${searchQuery}-${sourceType}-${filesFilter}-${networkScope}-${page}`}
        fallback={
          <div className="flex h-64 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <SkillsContent
          viewMode={viewMode}
          searchQuery={searchQuery}
          page={page}
          sourceType={sourceType}
          hasFiles={hasFiles}
          networkScope={networkScope}
        />
      </Suspense>
    </ContentBlock>
  );
}
