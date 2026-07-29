import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import TriggersContent from "./components/TriggersContent";
import TriggersDisplayMenu from "./components/TriggersDisplayMenu";
import TriggersHeaderTabs from "./components/TriggersHeaderTabs";
import TriggersSkeleton from "./components/TriggersSkeleton";
import TriggersToolbar from "./components/TriggersToolbar";
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
      className="p-0 overflow-hidden"
    >
      <div className="flex h-full w-full flex-col">
        <TriggersToolbar
          searchPlaceholder={t("searchPlaceholder")}
          filterSlot={
            <Suspense fallback={<div className="h-7 w-48" />}>
              <TriggersTypeFilterSection currentType={typeFilter} />
            </Suspense>
          }
          tabsSlot={
            <div className="flex items-center gap-2">
              <TriggersDisplayMenu currentGroup={groupBy} />
              <TriggersHeaderTabs currentTab={viewMode} />
            </div>
          }
        />

        <div className="min-h-0 flex-1 overflow-auto px-4 py-5">
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
        </div>
      </div>
    </ContentBlock>
  );
}
