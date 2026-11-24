import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import FeedSkeleton from "./components/feed/FeedSkeleton";
import FeedToolbar from "./components/feed/FeedToolbar";

export default async function Loading() {
  const t = await getTranslations("EventsPage");
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
      }}
      subheader={
        <FeedToolbar streams={[]} platformStreams={[]} sourceTypes={[]} />
      }
    >
      <FeedSkeleton />
    </ContentBlock>
  );
}
