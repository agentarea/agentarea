import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import SearchInput from "@/components/SearchInput";
import CreateSkillButton from "./components/CreateSkillButton";
import SkillsFilters from "./components/SkillsFilters";
import SkillsHeaderTabs from "./components/SkillsHeaderTabs";
import SkillsList from "./components/SkillsList";

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
          <SearchInput urlParamName="search" urlPath="/skills" />
          <div className="flex shrink-0 items-center gap-3">
            <SkillsFilters
              sourceType={sourceType}
              filesFilter={filesFilter}
              networkScope={networkScope}
            />
            <SkillsHeaderTabs currentTab={viewMode} />
          </div>
        </>
      }
    >
      <SkillsList
        viewMode={viewMode}
        searchQuery={searchQuery}
        sourceType={sourceType}
        hasFiles={hasFiles}
        networkScope={networkScope}
      />
    </ContentBlock>
  );
}
