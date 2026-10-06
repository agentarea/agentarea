import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { ViewModeTabs } from "@/components/HeaderTabs";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import StreamsContent from "./components/StreamsContent";
import StreamsSkeleton from "./components/StreamsSkeleton";

export const metadata: Metadata = { title: "Events" };

export default async function EventsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("EventsPage");
  const params = await searchParams;
  const cookieTab = (await cookies()).get("tab_events")?.value;
  const viewMode =
    typeof params.tab === "string" ? params.tab : cookieTab || "table";
  const search = typeof params.search === "string" ? params.search : "";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
      }}
      subheader={
        <SubheaderToolbar
          search={
            <SearchInput
              urlParamName="search"
              urlPath="/events"
              placeholder={t("searchPlaceholder")}
            />
          }
          controls={<ViewModeTabs currentTab={viewMode} defaultTab="table" />}
        />
      }
    >
      <Suspense
        key={`${search}-${viewMode}`}
        fallback={<StreamsSkeleton viewMode={viewMode} />}
      >
        <StreamsContent search={search} viewMode={viewMode} />
      </Suspense>
    </ContentBlock>
  );
}
