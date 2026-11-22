import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import FeedSkeleton from "../components/feed/FeedSkeleton";

export default async function Loading() {
  const t = await getTranslations("EventsPage");
  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: t("title"), href: "/events" }] }}
    >
      <FeedSkeleton />
    </ContentBlock>
  );
}
