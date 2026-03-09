import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import SearchInput from "@/components/SearchInput";
import SkillsContent from "./components/SkillsContent";
import SkillsHeaderTabs from "./components/SkillsHeaderTabs";
import CreateSkillButton from "./components/CreateSkillButton";

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
          <SkillsHeaderTabs currentTab={viewMode} />
        </>
      }
    >
      <Suspense key={`${viewMode}-${searchQuery}`} fallback={
        <div className="flex h-64 items-center justify-center">
          <LoadingSpinner />
        </div>
      }>
        <SkillsContent
          viewMode={viewMode}
          searchQuery={searchQuery}
        />
      </Suspense>
    </ContentBlock>
  );
}
