import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { ViewModeTabs } from "@/components/HeaderTabs";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import EventsSectionTabs from "../components/EventsSectionTabs";
import StreamsSkeleton from "../components/StreamsSkeleton";

export default async function Loading() {
  const t = await getTranslations("EventsPage");
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("streamsDescription"),
      }}
      subheader={
        <SubheaderToolbar
          categories={<EventsSectionTabs />}
          search={
            <SearchInput
              urlParamName="search"
              urlPath="/events/streams"
              placeholder={t("searchPlaceholder")}
            />
          }
          controls={<ViewModeTabs currentTab="table" defaultTab="table" />}
        />
      }
    >
      <StreamsSkeleton viewMode="table" />
    </ContentBlock>
  );
}
