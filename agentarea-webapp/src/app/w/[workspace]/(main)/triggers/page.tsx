import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { ViewModeTabs } from "@/components/HeaderTabs";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { readUiPrefs } from "@/lib/ui-prefs-server";
import CreateTriggerButton from "./components/CreateTriggerButton";
import TriggersContent from "./components/TriggersContent";
import TriggersDisplayMenu from "./components/TriggersDisplayMenu";
import TriggersSkeleton from "./components/TriggersSkeleton";
import TriggersTypeFilterSection from "./components/TriggersTypeFilterSection";

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

  // Read tab from URL, else the remembered view
  const uiPrefs = await readUiPrefs();
  const cookieTab = uiPrefs.views["tab_triggers"];
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

  const groupBy =
    resolvedSearchParams.group === "none"
      ? ("none" as const)
      : ("channel" as const);

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: <CreateTriggerButton />,
      }}
      subheader={
        <SubheaderToolbar
          categories={
            <Suspense fallback={<div className="h-7" />}>
              <TriggersTypeFilterSection currentType={typeFilter} />
            </Suspense>
          }
          search={
            <SearchInput
              urlParamName="search"
              urlPath="/triggers"
              placeholder={t("searchPlaceholder")}
            />
          }
          controls={
            <>
              <TriggersDisplayMenu currentGroup={groupBy} />
              <ViewModeTabs currentTab={viewMode} defaultTab="table" />
            </>
          }
        />
      }
    >
      <Suspense
        key={`${viewMode}-${searchQuery}-${typeFilter}-${groupBy}`}
        fallback={<TriggersSkeleton viewMode={viewMode} />}
      >
        <TriggersContent
          viewMode={viewMode}
          searchQuery={searchQuery}
          typeFilter={typeFilter}
          groupBy={groupBy}
        />
      </Suspense>
    </ContentBlock>
  );
}
