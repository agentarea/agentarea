import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import SearchInput from "@/components/SearchInput";
import TriggersContent from "./components/TriggersContent";
import TriggersHeaderTabs from "./components/TriggersHeaderTabs";
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
        controls: <CreateTriggerButton />,
      }}
      subheader={
        <>
          <SearchInput urlParamName="search" urlPath="/triggers" />
          <TriggersHeaderTabs currentTab={viewMode} />
        </>
      }
    >
      <Suspense key={`${viewMode}-${searchQuery}`} fallback={
        <div className="flex h-64 items-center justify-center">
          <LoadingSpinner />
        </div>
      }>
        <TriggersContent
          viewMode={viewMode}
          searchQuery={searchQuery}
        />
      </Suspense>
    </ContentBlock>
  );
}
