import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import TriggersSkeleton from "../triggers/components/TriggersSkeleton";
import ChannelsContent from "./components/ChannelsContent";
import NewChannelButton from "./components/NewChannelButton";

export const metadata = { title: "Channels" };

export default async function ChannelsPage() {
  const t = await getTranslations("ChannelsPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
        controls: <NewChannelButton />,
      }}
    >
      <Suspense fallback={<TriggersSkeleton viewMode="table" />}>
        <ChannelsContent />
      </Suspense>
    </ContentBlock>
  );
}
