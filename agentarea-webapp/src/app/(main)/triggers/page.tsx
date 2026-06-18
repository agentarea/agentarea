import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import SearchInput from "@/components/SearchInput";
import TriggersContent from "./components/TriggersContent";
import TriggersHeaderTabs from "./components/TriggersHeaderTabs";
import TriggersTypeFilterSection from "./components/TriggersTypeFilterSection";
import CreateTriggerButton from "./components/CreateTriggerButton";

export const metadata = {
  title: "Automation",
};

export default async function TriggersPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("TriggersPage");
  const resolvedSearchParams = await searchParams;

  // Read tab from URL or fallback to cookie
  const cookieStore = await cookies();
  const cookieTab = cookieStore.get("tab_triggers")?.value;
  const viewMode =
    typeof resolvedSearchParams.tab === "string"
      ? (resolvedSearchParams.tab as "grid" | "table")
      : (cookieTab as "grid" | "table") || "table";

  const searchQuery =
    typeof resolvedSearchParams.search === "string"
      ? resolvedSearchParams.search
      : "";

  const typeFilter =
    typeof resolvedSearchParams.type === "string"
      ? resolvedSearchParams.type
      : "all";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: <CreateTriggerButton />,
      }}
      subheader={
        <>
          <Suspense fallback={<div className="h-7" />}>
            <TriggersTypeFilterSection currentType={typeFilter} />
          </Suspense>
          <div className="flex flex-1 items-center justify-end gap-3">
            <SearchInput
              urlParamName="search"
              urlPath="/triggers"
              placeholder={t("searchPlaceholder")}
            />
            <TriggersHeaderTabs currentTab={viewMode} />
          </div>
        </>
      }
    >
      <Suspense key={`${viewMode}-${searchQuery}-${typeFilter}`} fallback={
        <div className="flex h-64 items-center justify-center">
          <LoadingSpinner />
        </div>
      }>
        <TriggersContent
          viewMode={viewMode}
          searchQuery={searchQuery}
          typeFilter={typeFilter}
        />
      </Suspense>
    </ContentBlock>
  );
}
