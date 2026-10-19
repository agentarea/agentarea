import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import FeedSkeleton, { FEED_GRID } from "./components/feed/FeedSkeleton";

export default async function Loading() {
  const t = await getTranslations("EventsPage");
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
      }}
    >
      <div className={FEED_GRID}>
        <FeedSkeleton />
      </div>
    </ContentBlock>
  );
}
